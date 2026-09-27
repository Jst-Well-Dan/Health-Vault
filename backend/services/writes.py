"""批量写入的共享 service 层（终端 CLI 与 REST 共用）。

``import_visit_json.py`` 与各 router 只做参数解析与 HTTP 映射，
校验、事务写入、复核查询都收敛到这里，保证两边行为一致。

注意：本模块不决定备份策略。自动备份仍只发生在批量 ``--write``
与启动期结构迁移；前端单条小写入不调这里的备份。
"""

import json
import re
import secrets
from pathlib import Path

import database
from database import get_conn
from routers.common import bool_out, json_dumps, json_loads, row_to_dict

PROJECT_DIR = Path(__file__).resolve().parents[2]

SEVERITIES = {None, "严重", "一般", "轻微"}
LAB_STATUSES = {"normal", "high", "low", "abnormal", "unknown", None}


class PayloadError(Exception):
    """payload 不合法，拒绝写入。"""


def _date(value: object, field: str) -> str:
    from datetime import datetime

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


def validate_bundle(payload: dict, member_override: str | None) -> dict:
    """校验 payload，返回可直接写入的 plan（含重复就诊提醒）。只读，不写库。"""
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


def insert_bundle(plan: dict) -> dict:
    """一个事务写入就诊 1 条 + 化验/用药/附件 N 条。返回 visit_id 与 attachment_ids。"""
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


def verify_bundle(visit_id: int, plan: dict) -> dict:
    """按 visit_id 重查行数，与 plan 期望条数比对。只读。"""
    with get_conn() as conn:
        counted = {
            "labs": conn.execute("SELECT COUNT(*) AS c FROM lab_results WHERE visit_id = ?", (visit_id,)).fetchone()["c"],
            "meds": conn.execute("SELECT COUNT(*) AS c FROM meds WHERE visit_id = ?", (visit_id,)).fetchone()["c"],
            "attachments": conn.execute("SELECT COUNT(*) AS c FROM attachments WHERE visit_id = ?", (visit_id,)).fetchone()["c"],
            "visits": conn.execute("SELECT COUNT(*) AS c FROM visits WHERE id = ?", (visit_id,)).fetchone()["c"],
        }
    expected = {"labs": len(plan["labs"]), "meds": len(plan["meds"]), "attachments": len(plan["attachments"]), "visits": 1}
    return {"counts": counted, "expected": expected, "ok": counted == expected}


def describe_plan(plan: dict) -> str:
    """dry-run 展示文本：成员、就诊、条数、重复提醒、库路径。"""
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


class LinkedRecordsError(Exception):
    """就诊仍有关联子记录，拒绝删除（router 映射为 HTTP 409）。"""


def _visit_out(row) -> dict:
    item = dict(row)
    item["diagnosis"] = json_loads(item.get("diagnosis"))
    return item


def create_visit_record(**fields) -> dict:
    """单条新增就诊。`diagnosis` 传 list；成员不存在抛 PayloadError。"""
    with get_conn() as conn:
        member = conn.execute("SELECT key FROM members WHERE key = ?", (fields.get("member_key"),)).fetchone()
        if member is None:
            raise PayloadError("成员不存在")
        cur = conn.execute(
            """
            INSERT INTO visits
              (member_key, date, type, hospital, department, doctor, chief_complaint,
               severity, diagnosis, notes, note_full, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields.get("member_key"), fields.get("date"), fields.get("type"), fields.get("hospital"),
                fields.get("department"), fields.get("doctor"), fields.get("chief_complaint"),
                fields.get("severity"), json_dumps(fields.get("diagnosis")), fields.get("notes"),
                fields.get("note_full"), fields.get("source_file"),
            ),
        )
        return _visit_out(conn.execute("SELECT * FROM visits WHERE id = ?", (cur.lastrowid,)).fetchone())


def update_visit_record(visit_id: int, data: dict) -> dict:
    """单条更新就诊。空 data 直接返回当前行；不存在抛 PayloadError。"""
    with get_conn() as conn:
        if conn.execute("SELECT id FROM visits WHERE id = ?", (visit_id,)).fetchone() is None:
            raise PayloadError("就诊记录不存在")
        if data:
            if "diagnosis" in data:
                data["diagnosis"] = json_dumps(data["diagnosis"])
            conn.execute(
                f"UPDATE visits SET {', '.join(f'{field} = ?' for field in data)} WHERE id = ?",
                [*data.values(), visit_id],
            )
        return _visit_out(conn.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone())


def delete_visit_record(visit_id: int) -> dict:
    """单条删除就诊。仍有关联子记录抛 LinkedRecordsError；不存在抛 PayloadError。"""
    with get_conn() as conn:
        if conn.execute("SELECT id FROM visits WHERE id = ?", (visit_id,)).fetchone() is None:
            raise PayloadError("就诊记录不存在")
        counts = {
            "化验": conn.execute("SELECT COUNT(*) FROM lab_results WHERE visit_id = ?", (visit_id,)).fetchone()[0],
            "用药": conn.execute("SELECT COUNT(*) FROM meds WHERE visit_id = ?", (visit_id,)).fetchone()[0],
            "附件": conn.execute("SELECT COUNT(*) FROM attachments WHERE visit_id = ?", (visit_id,)).fetchone()[0],
        }
        if any(counts.values()):
            linked_text = "/".join(f"{count} 项{name}" for name, count in counts.items() if count)
            raise LinkedRecordsError(f"就诊记录仍关联 {linked_text}，需先解除关联或分别处理")
        conn.execute("DELETE FROM visits WHERE id = ?", (visit_id,))
    return {"ok": True, "id": visit_id}


class VisitMismatchError(Exception):
    """关联就诊不属于当前成员（router 映射为 HTTP 422）。"""


def _visit_owner(conn, visit_id: int) -> dict:
    visit = conn.execute("SELECT member_key FROM visits WHERE id = ?", (visit_id,)).fetchone()
    if visit is None:
        raise PayloadError("关联就诊记录不存在")
    return visit


def _check_visit_owner(conn, visit_id: int | None, member_key: str) -> None:
    if visit_id is None:
        return
    if _visit_owner(conn, visit_id)["member_key"] != member_key:
        raise VisitMismatchError("关联就诊记录不属于当前成员")


def create_lab_record(**fields) -> dict:
    """单条新增化验。成员/就诊不存在抛 PayloadError；就诊属主不符抛 VisitMismatchError。"""
    with get_conn() as conn:
        if conn.execute("SELECT key FROM members WHERE key = ?", (fields.get("member_key"),)).fetchone() is None:
            raise PayloadError("成员不存在")
        _check_visit_owner(conn, fields.get("visit_id"), fields.get("member_key"))
        cur = conn.execute(
            """
            INSERT INTO lab_results
              (member_key, visit_id, date, panel, test_name, value, unit, ref_low, ref_high, status, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields.get("member_key"), fields.get("visit_id"), fields.get("date"), fields.get("panel"),
                fields.get("test_name"), fields.get("value"), fields.get("unit"), fields.get("ref_low"),
                fields.get("ref_high"), fields.get("status"), fields.get("source_file"),
            ),
        )
        return row_to_dict(conn.execute("SELECT * FROM lab_results WHERE id = ?", (cur.lastrowid,)).fetchone())


def update_lab_record(lab_id: int, data: dict) -> dict:
    """单条更新化验。不存在抛 PayloadError；就诊属主不符抛 VisitMismatchError。"""
    with get_conn() as conn:
        current = conn.execute("SELECT id, member_key FROM lab_results WHERE id = ?", (lab_id,)).fetchone()
        if current is None:
            raise PayloadError("化验记录不存在")
        _check_visit_owner(conn, data.get("visit_id"), current["member_key"])
        if data:
            conn.execute(
                f"UPDATE lab_results SET {', '.join(f'{field} = ?' for field in data)} WHERE id = ?",
                [*data.values(), lab_id],
            )
        return row_to_dict(conn.execute("SELECT * FROM lab_results WHERE id = ?", (lab_id,)).fetchone())


def delete_lab_record(lab_id: int) -> dict:
    """单条删除化验。不存在抛 PayloadError。"""
    with get_conn() as conn:
        if conn.execute("SELECT id FROM lab_results WHERE id = ?", (lab_id,)).fetchone() is None:
            raise PayloadError("化验记录不存在")
        conn.execute("DELETE FROM lab_results WHERE id = ?", (lab_id,))
    return {"ok": True, "id": lab_id}


def _med_out(row) -> dict:
    return bool_out(dict(row), "ongoing")


def create_med_record(**fields) -> dict:
    """单条新增用药。`ongoing` 传 bool。"""
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO meds
              (member_key, visit_id, name, dose, freq, route, start_date, end_date, ongoing, category, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields.get("member_key"), fields.get("visit_id"), fields.get("name"),
                fields.get("dose"), fields.get("freq"), fields.get("route"),
                fields.get("start_date"), fields.get("end_date"),
                1 if fields.get("ongoing") else 0, fields.get("category"), fields.get("notes"),
            ),
        )
        return _med_out(conn.execute("SELECT * FROM meds WHERE id = ?", (cur.lastrowid,)).fetchone())


def update_med_record(med_id: int, data: dict) -> dict:
    """单条更新用药（附带 updated_at）。不存在抛 PayloadError("记录不存在")。"""
    if data:
        updates = []
        values = []
        for field, value in data.items():
            if field == "ongoing":
                value = 1 if value else 0
            updates.append(f"{field} = ?")
            values.append(value)
        updates.append("updated_at = datetime('now','localtime')")
        values.append(med_id)
        with get_conn() as conn:
            if conn.execute("SELECT id FROM meds WHERE id = ?", (med_id,)).fetchone() is None:
                raise PayloadError("记录不存在")
            conn.execute(f"UPDATE meds SET {', '.join(updates)} WHERE id = ?", values)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM meds WHERE id = ?", (med_id,)).fetchone()
        if row is None:
            raise PayloadError("记录不存在")
        return _med_out(row)


def delete_med_record(med_id: int) -> dict:
    """单条删除用药。不存在抛 PayloadError("记录不存在")。"""
    with get_conn() as conn:
        if conn.execute("SELECT id FROM meds WHERE id = ?", (med_id,)).fetchone() is None:
            raise PayloadError("记录不存在")
        conn.execute("DELETE FROM meds WHERE id = ?", (med_id,))
    return {"ok": True}


ATTACHMENT_UPDATE_FIELDS = {"visit_id", "date", "title", "org", "tag", "file_path", "notes"}


def create_attachment_record(**fields) -> dict:
    """单条新增附件。`file_path` 由调用方先做路径归一化（router 负责 403）。"""
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO attachments
              (member_key, visit_id, date, title, org, tag, filename, file_path, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields.get("member_key"), fields.get("visit_id"), fields.get("date"), fields.get("title"),
                fields.get("org"), fields.get("tag"), fields.get("filename"), fields.get("file_path"),
                fields.get("notes"),
            ),
        )
        return row_to_dict(conn.execute("SELECT * FROM attachments WHERE id = ?", (cur.lastrowid,)).fetchone())


def update_attachment_record(attachment_id: int, data: dict) -> dict:
    """单条更新附件。不存在抛 PayloadError；就诊属主不符抛 VisitMismatchError。"""
    data = {key: value for key, value in data.items() if key in ATTACHMENT_UPDATE_FIELDS}
    with get_conn() as conn:
        attachment = conn.execute("SELECT member_key FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
        if attachment is None:
            raise PayloadError("附件不存在")
        _check_visit_owner(conn, data.get("visit_id"), attachment["member_key"])
        if data:
            conn.execute(
                f"UPDATE attachments SET {', '.join(f'{field} = ?' for field in data)} WHERE id = ?",
                [*data.values(), attachment_id],
            )
        return row_to_dict(conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone())


def delete_attachment_record(attachment_id: int) -> dict:
    """单条删除附件行（文件删除由 router 处理）。不存在抛 PayloadError。"""
    with get_conn() as conn:
        if conn.execute("SELECT id FROM attachments WHERE id = ?", (attachment_id,)).fetchone() is None:
            raise PayloadError("附件不存在")
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    return {"ok": True}


def create_weight_record(**fields) -> dict:
    """单条新增体重。"""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO weight_log (member_key, date, weight_kg, notes) VALUES (?, ?, ?, ?)",
            (fields.get("member_key"), fields.get("date"), fields.get("weight_kg"), fields.get("notes")),
        )
        return row_to_dict(conn.execute("SELECT * FROM weight_log WHERE id = ?", (cur.lastrowid,)).fetchone())


def delete_weight_record(weight_id: int) -> dict:
    """单条删除体重。不存在抛 PayloadError("记录不存在")。"""
    with get_conn() as conn:
        if conn.execute("SELECT id FROM weight_log WHERE id = ?", (weight_id,)).fetchone() is None:
            raise PayloadError("记录不存在")
        conn.execute("DELETE FROM weight_log WHERE id = ?", (weight_id,))
    return {"ok": True}


def _check_care_kind(kind) -> None:
    if kind not in database.PET_CARE_KINDS:
        raise ValidationError(f"kind 仅支持：{'、'.join(database.PET_CARE_KINDS)}")


def create_care_log_record(**fields) -> dict:
    """单条新增记事。kind 不在白名单抛 ValidationError。"""
    _check_care_kind(fields.get("kind"))
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO pet_care_logs (member_key, date, kind, notes)
            VALUES (?, ?, ?, ?)
            """,
            (fields.get("member_key"), fields.get("date"), fields.get("kind"), fields.get("notes")),
        )
        return row_to_dict(conn.execute("SELECT * FROM pet_care_logs WHERE id = ?", (cur.lastrowid,)).fetchone())


def update_care_log_record(log_id: int, data: dict) -> dict:
    """单条更新记事。不存在抛 PayloadError("记事不存在")；kind 不在白名单抛 ValidationError。"""
    with get_conn() as conn:
        if conn.execute("SELECT id FROM pet_care_logs WHERE id = ?", (log_id,)).fetchone() is None:
            raise PayloadError("记事不存在")
        data.pop("title", None)  # title 列已删除，忽略旧客户端残留字段。
        if "kind" in data:
            _check_care_kind(data.get("kind"))
        if data:
            updates = [f"{field} = ?" for field in data]
            values = list(data.values()) + [log_id]
            conn.execute(f"UPDATE pet_care_logs SET {', '.join(updates)} WHERE id = ?", values)
        return row_to_dict(conn.execute("SELECT * FROM pet_care_logs WHERE id = ?", (log_id,)).fetchone())


def delete_care_log_record(log_id: int) -> dict:
    """单条删除记事。不存在抛 PayloadError("记事不存在")。"""
    with get_conn() as conn:
        if conn.execute("SELECT id FROM pet_care_logs WHERE id = ?", (log_id,)).fetchone() is None:
            raise PayloadError("记事不存在")
        conn.execute("DELETE FROM pet_care_logs WHERE id = ?", (log_id,))
    return {"ok": True}


class ValidationError(Exception):
    """输入形状/业务规则不合法（router 映射为 HTTP 422）。"""


class ConflictError(Exception):
    """资源已存在（router 映射为 HTTP 409）。"""


SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
ALLOWED_SPECIES = {"human", "cat", "dog", "other"}
MEMBER_CREATE_FIELDS = {
    "key", "name", "full_name", "initial", "birth_date", "sex", "blood_type", "role",
    "species", "species_detail", "sort_order", "breed", "home_date", "doctor", "allergies", "chronic", "notes",
}
MEMBER_UPDATE_FIELDS = {
    "name", "full_name", "initial", "birth_date", "sex", "blood_type", "role",
    "species", "species_detail", "sort_order", "breed", "home_date", "doctor", "allergies", "chronic", "notes", "archived_at",
}


def validate_member_key(key: str) -> str:
    key = str(key or "").strip()
    if not SAFE_KEY_RE.fullmatch(key):
        raise ValidationError("成员 key 只能包含 1-64 位英文字母、数字、下划线或连字符，且必须以字母或数字开头")
    return key


def _member_sex(species: str, sex) -> str | None:
    if sex is None or not str(sex).strip():
        return None
    sex = str(sex).strip()
    allowed_sex = {"男", "女"} if species == "human" else {"弟弟", "妹妹"}
    if sex not in allowed_sex:
        raise ValidationError(f"{species} 的性别仅支持：{'、'.join(sorted(allowed_sex))}")
    return sex


def _member_species(value) -> str:
    species = str(value or "").strip()
    if not species:
        raise ValidationError("species 不能为空")
    if species not in ALLOWED_SPECIES:
        raise ValidationError(f"species 仅支持：{', '.join(sorted(ALLOWED_SPECIES))}")
    return species


def create_member_record(data: dict) -> str:
    """单条新增成员。返回新成员 key；失败抛 ValidationError/ConflictError。"""
    data = dict(data)
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("成员姓名不能为空")
    species = _member_species(data.get("species"))
    data["sex"] = _member_sex(species, data.get("sex"))
    data["name"] = name
    data["species"] = species
    with get_conn() as conn:
        key = data.get("key")
        if key:
            key = validate_member_key(key)
            if conn.execute("SELECT 1 FROM members WHERE key = ?", (key,)).fetchone():
                raise ConflictError("成员 key 已存在")
        else:
            prefix = "member" if species == "human" else "pet"
            for _ in range(10):
                key = f"{prefix}-{secrets.token_hex(4)}"
                if not conn.execute("SELECT 1 FROM members WHERE key = ?", (key,)).fetchone():
                    break
            else:
                raise RuntimeError("无法生成唯一成员 key")
        data["key"] = key
        if data.get("sort_order") is None:
            max_sort_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS value FROM members").fetchone()["value"]
            data["sort_order"] = max_sort_order + 10
        fields = []
        values = []
        for field in MEMBER_CREATE_FIELDS:
            if field not in data:
                continue
            value = data[field]
            if field in {"allergies", "chronic"}:
                value = json_dumps(value)
            fields.append(field)
            values.append(value)
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(f"INSERT INTO members ({', '.join(fields)}) VALUES ({placeholders})", values)
    return key


def update_member_record(key: str, data: dict) -> str:
    """单条更新成员。返回 key；不存在抛 PayloadError，形状错抛 ValidationError。"""
    data = dict(data)
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValidationError("成员姓名不能为空")
        data["name"] = name
    if "species" in data:
        data["species"] = _member_species(data.get("species"))
    if "sex" in data:
        current_species = data.get("species")
        if current_species is None:
            with get_conn() as conn:
                row = conn.execute("SELECT species FROM members WHERE key = ?", (key,)).fetchone()
                if row is None:
                    raise PayloadError("成员不存在")
                current_species = row["species"]
        data["sex"] = _member_sex(current_species, data.get("sex"))
    updates = []
    values = []
    for field, value in data.items():
        if field not in MEMBER_UPDATE_FIELDS:
            continue
        if field in {"allergies", "chronic"}:
            value = json_dumps(value)
        updates.append(f"{field} = ?")
        values.append(value)
    updates.append("updated_at = datetime('now','localtime')")
    values.append(key)
    with get_conn() as conn:
        if conn.execute("SELECT key FROM members WHERE key = ?", (key,)).fetchone() is None:
            raise PayloadError("成员不存在")
        conn.execute(f"UPDATE members SET {', '.join(updates)} WHERE key = ?", values)
    return key
