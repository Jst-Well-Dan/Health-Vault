"""按 JSON payload 写入就诊/化验/用药/附件记录。

这是「终端 pi + skill」写入路径的唯一落地脚本：
模型只负责把报告整理成 JSON，真正写库、备份、校验都由这里做。

用法::

    python backend/scripts/import_visit_json.py --file payload.json --dry-run
    python backend/scripts/import_visit_json.py --file payload.json --write

安全边界：
* ``--dry-run`` 只读，不写库、不备份；``--write`` 才会先自动备份再事务写入。
* 成员不存在、日期格式错误、附件路径不存在、疑似重复就诊都会拒绝写入。
* 写入后重新查询核对行数，并打印 visit_id、影响行数与备份路径。
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

import database  # noqa: E402
from database import get_conn  # noqa: E402
from routers.common import json_dumps  # noqa: E402
from services.backups import create_database_backup  # noqa: E402

SEVERITIES = {None, "严重", "一般", "轻微"}
LAB_STATUSES = {"normal", "high", "low", "abnormal", "unknown", None}
VISIT_TYPES = {"就医", "体检", "复查", "疫苗"}


class PayloadError(Exception):
    """payload 不合法，拒绝写入。"""


def _date(value: object, field: str) -> str:
    text = str(value or "").strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise PayloadError(f"{field} 必须是 YYYY-MM-DD，当前是 {text!r}") from exc
    return text


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_payload(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PayloadError(f"找不到 payload 文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise PayloadError(f"payload 不是合法 JSON（第 {exc.lineno} 行）：{exc.msg}") from exc
    if not isinstance(payload, dict):
        raise PayloadError("payload 顶层必须是 JSON 对象")
    return payload


def validate(payload: dict, member_override: str | None) -> dict:
    visit = payload.get("visit")
    if not isinstance(visit, dict):
        raise PayloadError("payload 缺少 visit 对象")

    member_key = _text(member_override) or _text(visit.get("member_key")) or _text(payload.get("member_key"))
    if not member_key:
        raise PayloadError("缺少 member_key（放在 visit 里或用 --member 指定）")

    date = _date(visit.get("date"), "visit.date")
    severity = _text(visit.get("severity"))
    if severity not in SEVERITIES:
        raise PayloadError("visit.severity 只能是 严重/一般/轻微 或留空")

    diagnosis = visit.get("diagnosis") or []
    if not isinstance(diagnosis, list) or any(not isinstance(item, str) for item in diagnosis):
        raise PayloadError("visit.diagnosis 必须是字符串数组")
    if not _text(visit.get("notes")) or not _text(visit.get("note_full")):
        raise PayloadError("visit.notes 和 visit.note_full 必填（不要把摘要留空）")

    labs: list[dict] = []
    for index, lab in enumerate(payload.get("labs") or [], start=1):
        if not isinstance(lab, dict):
            raise PayloadError(f"labs[{index}] 必须是对象")
        if not _text(lab.get("panel")) or not _text(lab.get("test_name")):
            raise PayloadError(f"labs[{index}] 缺少 panel 或 test_name")
        if _text(lab.get("status")) not in LAB_STATUSES:
            raise PayloadError(f"labs[{index}].status 只能是 normal/high/low/abnormal/unknown 或留空")
        labs.append(lab)

    meds: list[dict] = []
    for index, med in enumerate(payload.get("meds") or [], start=1):
        if not isinstance(med, dict) or not _text(med.get("name")):
            raise PayloadError(f"meds[{index}] 缺少 name")
        entry = dict(med)
        if entry.get("start_date"):
            entry["start_date"] = _date(entry["start_date"], f"meds[{index}].start_date")
        if entry.get("end_date"):
            entry["end_date"] = _date(entry["end_date"], f"meds[{index}].end_date")
        meds.append(entry)

    attachments: list[dict] = []
    missing_files: list[str] = []
    for index, attachment in enumerate(payload.get("attachments") or [], start=1):
        if not isinstance(attachment, dict) or not _text(attachment.get("title")):
            raise PayloadError(f"attachments[{index}] 缺少 title")
        relative = _text(attachment.get("file_path"))
        if relative:
            candidate = (PROJECT_DIR / relative).resolve()
            if not candidate.is_file():
                missing_files.append(relative)
        attachments.append(attachment)

    if missing_files:
        raise PayloadError("附件文件不存在，先把报告归档到 data/reports/... 再写库：\n  - " + "\n  - ".join(missing_files))

    with get_conn() as conn:
        member = conn.execute("SELECT key, name FROM members WHERE key = ?", (member_key,)).fetchone()
        duplicates = [
            dict(row)
            for row in conn.execute(
                "SELECT id, date, hospital, chief_complaint FROM visits WHERE member_key = ? AND date = ?",
                (member_key, date),
            ).fetchall()
        ]
    if not member:
        raise PayloadError(f"成员不存在：{member_key}")

    return {
        "member_key": member_key,
        "member_name": member["name"],
        "date": date,
        "visit": visit,
        "labs": labs,
        "meds": meds,
        "attachments": attachments,
        "duplicates": duplicates,
    }


def _insert(plan: dict) -> dict:
    visit = plan["visit"]
    member_key = plan["member_key"]
    date = plan["date"]
    source_file = _text(visit.get("source_file"))
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO visits (member_key, date, type, hospital, department, doctor, chief_complaint,
                                severity, diagnosis, notes, note_full, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                member_key, date, _text(visit.get("type")) or "体检", _text(visit.get("hospital")),
                _text(visit.get("department")), _text(visit.get("doctor")), _text(visit.get("chief_complaint")),
                _text(visit.get("severity")), json_dumps(visit.get("diagnosis")), _text(visit.get("notes")),
                _text(visit.get("note_full")), source_file,
            ),
        )
        visit_id = cursor.lastrowid
        for lab in plan["labs"]:
            conn.execute(
                """
                INSERT INTO lab_results (member_key, visit_id, date, panel, test_name, value, unit,
                                         ref_low, ref_high, status, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    member_key, visit_id, date, _text(lab.get("panel")), _text(lab.get("test_name")),
                    _text(lab.get("value")), _text(lab.get("unit")), _text(lab.get("ref_low")),
                    _text(lab.get("ref_high")), _text(lab.get("status")) or "unknown",
                    _text(lab.get("source_file")) or source_file,
                ),
            )
        for med in plan["meds"]:
            conn.execute(
                """
                INSERT INTO meds (member_key, visit_id, name, dose, freq, route, start_date, end_date,
                                  ongoing, category, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    member_key, visit_id, _text(med.get("name")), _text(med.get("dose")), _text(med.get("freq")),
                    _text(med.get("route")), med.get("start_date") or date, med.get("end_date"),
                    1 if med.get("ongoing") else 0, _text(med.get("category")), _text(med.get("notes")),
                ),
            )
        attachment_ids = []
        for attachment in plan["attachments"]:
            cursor = conn.execute(
                """
                INSERT INTO attachments (member_key, visit_id, date, title, org, tag, filename, file_path, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    member_key, visit_id, date, _text(attachment.get("title")),
                    _text(attachment.get("org")) or _text(visit.get("hospital")), _text(attachment.get("tag")),
                    _text(attachment.get("filename")), _text(attachment.get("file_path")),
                    _text(attachment.get("notes")),
                ),
            )
            attachment_ids.append(cursor.lastrowid)
    return {"visit_id": visit_id, "attachment_ids": attachment_ids}


def verify(visit_id: int, plan: dict) -> dict:
    with get_conn() as conn:
        counted = {
            "labs": conn.execute("SELECT COUNT(*) AS c FROM lab_results WHERE visit_id = ?", (visit_id,)).fetchone()["c"],
            "meds": conn.execute("SELECT COUNT(*) AS c FROM meds WHERE visit_id = ?", (visit_id,)).fetchone()["c"],
            "attachments": conn.execute("SELECT COUNT(*) AS c FROM attachments WHERE visit_id = ?", (visit_id,)).fetchone()["c"],
            "visits": conn.execute("SELECT COUNT(*) AS c FROM visits WHERE id = ?", (visit_id,)).fetchone()["c"],
        }
    expected = {"labs": len(plan["labs"]), "meds": len(plan["meds"]), "attachments": len(plan["attachments"]), "visits": 1}
    return {"counts": counted, "expected": expected, "ok": counted == expected}


def describe(plan: dict) -> str:
    visit = plan["visit"]
    lines = [
        f"成员：{plan['member_name']}（{plan['member_key']}）",
        f"就诊：{plan['date']} · {_text(visit.get('type')) or '体检'} · {_text(visit.get('hospital')) or '未填机构'}",
        f"诊断：{'；'.join(visit.get('diagnosis') or []) or '（空）'}",
        f"严重程度：{_text(visit.get('severity')) or '（空）'}",
        f"将写入：就诊 1 条、化验 {len(plan['labs'])} 条、用药 {len(plan['meds'])} 条、附件 {len(plan['attachments'])} 条",
    ]
    if plan["attachments"]:
        lines.append("附件：" + "、".join(_text(item.get("file_path")) or _text(item.get("filename")) or "?" for item in plan["attachments"]))
    if plan["duplicates"]:
        lines.append("注意：该成员当天已有就诊记录，确认不是重复录入：")
        for row in plan["duplicates"]:
            lines.append(f"  - visit_id={row['id']} {row['hospital'] or '未填机构'} · {row['chief_complaint'] or '无主诉'}")
    lines.append(f"数据库：{database.DB_PATH}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按 JSON payload 写入健康档案（默认只做 dry-run）")
    parser.add_argument("--file", required=True, type=Path, help="payload JSON 路径")
    parser.add_argument("--write", action="store_true", help="真正写入（会先自动备份）")
    parser.add_argument("--dry-run", action="store_true", help="只校验并打印将要写入的内容（默认行为）")
    parser.add_argument("--member", help="覆盖 payload 里的 member_key")
    parser.add_argument("--allow-duplicate", action="store_true", help="允许写入同一天已有就诊记录的成员")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果，便于脚本消费")
    args = parser.parse_args(argv)

    if args.write and args.dry_run:
        parser.error("--write 和 --dry-run 不能同时使用")

    try:
        plan = validate(load_payload(args.file), args.member)
    except PayloadError as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        return 1

    if plan["duplicates"] and args.write and not args.allow_duplicate:
        print("校验失败：同一天已有就诊记录，确认不是重复后用 --allow-duplicate 重跑。", file=sys.stderr)
        print(describe(plan), file=sys.stderr)
        return 1

    if not args.write:
        print("[dry-run] 未写入任何数据。\n" + describe(plan))
        if args.json:
            print(json.dumps({"ok": True, "mode": "dry-run", "plan": {"member_key": plan["member_key"], "date": plan["date"],
                                                                      "labs": len(plan["labs"]), "meds": len(plan["meds"]),
                                                                      "attachments": len(plan["attachments"]),
                                                                      "duplicates": plan["duplicates"]}}, ensure_ascii=False))
        return 0

    backup = create_database_backup(prefix="health")
    try:
        inserted = _insert(plan)
    except Exception as exc:  # 事务失败：给出可读原因，数据未落库
        print(f"写入失败（未提交）：{exc}\n已创建的备份：{backup['backup_path']}", file=sys.stderr)
        return 1

    result = verify(inserted["visit_id"], plan)
    print(f"已写入 visit_id={inserted['visit_id']}")
    print(f"影响行数：就诊 1、化验 {result['counts']['labs']}、用药 {result['counts']['meds']}、附件 {result['counts']['attachments']}")
    print(f"数据库：{database.DB_PATH}")
    print(f"备份：{backup['backup_path']}")
    if not result["ok"]:
        print(f"校验不一致（期望 {result['expected']}，实际 {result['counts']}）：请人工核对。", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "mode": "write", "visit_id": inserted["visit_id"], "counts": result["counts"],
                          "database_path": str(database.DB_PATH), "backup_path": backup["backup_path"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
