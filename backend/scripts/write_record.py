"""单记录写入 CLI（7 表共一个入口），供终端 pi 调用。

与前端 REST 白名单操作一一对应：有 REST 接口的操作才有子命令
（members 无删除、用归档代替；weight 无更新）。
批量成套写仍走 ``import_visit_json.py``，不要用这里逐条拼 visit。
记事 kind 白名单（驱虫/洗澡/换猫砂，见 database.PET_CARE_KINDS）由 service 校验，越界直接拒绝。

安全：
* 改、删先读当前行，打印 before/after 再执行。
* 单条不自动备份（与前端 REST 一致）；改错用时间戳备份恢复。
* 每次执行都打印实际数据库路径；mock 模式走测试夹具库。

用法::

    python backend/scripts/write_record.py labs add --data '{"member_key":"demo-self","date":"2026-04-01","panel":"血常规","test_name":"血红蛋白","value":"130","unit":"g/L","status":"normal"}'
    python backend/scripts/write_record.py meds update --id 6 --data '{"dose":"2片"}'
    python backend/scripts/write_record.py weight delete --id 13
    python backend/scripts/write_record.py members add --file new_member.json
"""

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import database  # noqa: E402
from database import get_conn  # noqa: E402
from routers.common import json_loads  # noqa: E402
from services import writes  # noqa: E402

TABLES = {
    "members": "members",
    "visits": "visits",
    "labs": "lab_results",
    "meds": "meds",
    "weight": "weight_log",
    "pet-care": "pet_care_logs",
    "attachments": "attachments",
}

OPS = {
    "members": {"add", "update"},
    "visits": {"add", "update", "delete"},
    "labs": {"add", "update", "delete"},
    "meds": {"add", "update", "delete"},
    "weight": {"add", "delete"},
    "pet-care": {"add", "update", "delete"},
    "attachments": {"add", "update", "delete"},
}


def _read_row(table: str, ident: str) -> dict | None:
    id_col = "key" if table == "members" else "id"
    with get_conn() as conn:
        row = conn.execute(f"SELECT * FROM {TABLES[table]} WHERE {id_col} = ?", (ident,)).fetchone()
        return dict(row) if row is not None else None


def _display(table: str, row: dict) -> dict:
    row = dict(row)
    if table == "visits":
        row["diagnosis"] = json_loads(row.get("diagnosis"))
    if table == "meds":
        row["ongoing"] = bool(row.get("ongoing"))
    if table == "members":
        row["allergies"] = json_loads(row.get("allergies"))
        row["chronic"] = json_loads(row.get("chronic"))
        row.pop("chip_id", None)
    return row


def _load_data(args) -> dict:
    if args.file:
        return json.loads(Path(args.file).read_text(encoding="utf-8"))
    if args.data:
        return json.loads(args.data)
    return {}


def _run(table: str, op: str, ident: str | None, data: dict):
    if table == "members":
        if op == "add":
            return {"key": writes.create_member_record(data)}
        return {"key": writes.update_member_record(ident, data)}
    if table == "visits":
        if op == "add":
            return writes.create_visit_record(**data)
        if op == "update":
            return writes.update_visit_record(int(ident), data)
        return writes.delete_visit_record(int(ident))
    if table == "labs":
        if op == "add":
            return writes.create_lab_record(**data)
        if op == "update":
            return writes.update_lab_record(int(ident), data)
        return writes.delete_lab_record(int(ident))
    if table == "meds":
        if op == "add":
            return writes.create_med_record(**data)
        if op == "update":
            return writes.update_med_record(int(ident), data)
        return writes.delete_med_record(int(ident))
    if table == "weight":
        if op == "add":
            return writes.create_weight_record(**data)
        return writes.delete_weight_record(int(ident))
    if table == "pet-care":
        if op == "add":
            return writes.create_care_log_record(**data)
        if op == "update":
            return writes.update_care_log_record(int(ident), data)
        return writes.delete_care_log_record(int(ident))
    if table == "attachments":
        if op == "add":
            return writes.create_attachment_record(**data)
        if op == "update":
            return writes.update_attachment_record(int(ident), data)
        return writes.delete_attachment_record(int(ident))
    raise writes.PayloadError(f"未知表：{table}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="单记录写入 7 表（与 REST 白名单一一对应）")
    parser.add_argument("table", choices=sorted(TABLES), help="表名")
    parser.add_argument("op", help="add/update/delete（各表可用操作不同）")
    parser.add_argument("--id", help="update/delete 的行标识（members 用 key，其余用数字 id）")
    parser.add_argument("--data", help="JSON 对象字符串")
    parser.add_argument("--file", help="JSON 文件路径（与 --data 二选一）")
    args = parser.parse_args(argv)

    if args.op not in OPS[args.table]:
        parser.error(f"{args.table} 不支持 {args.op}（可用：{', '.join(sorted(OPS[args.table]))}）")
    if args.op in {"update", "delete"} and not args.id:
        parser.error(f"{args.op} 必须带 --id")
    if args.data and args.file:
        parser.error("--data 和 --file 只能用一个")

    try:
        data = _load_data(args)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"输入解析失败：{exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("输入必须是 JSON 对象", file=sys.stderr)
        return 1

    before = _read_row(args.table, args.id) if args.op in {"update", "delete"} else None
    if args.op in {"update", "delete"} and before is None:
        print(f"记录不存在：{args.table} {args.id}", file=sys.stderr)
        return 1
    if before is not None:
        print("[before] " + json.dumps(_display(args.table, before), ensure_ascii=False))

    try:
        result = _run(args.table, args.op, args.id, data)
    except (writes.PayloadError, writes.ValidationError, writes.VisitMismatchError,
            writes.LinkedRecordsError, writes.ConflictError) as exc:
        print(f"写入拒绝：{exc}", file=sys.stderr)
        return 1

    if args.table == "members":
        after = _read_row("members", result["key"])
        print("[after] " + json.dumps(_display("members", after), ensure_ascii=False))
    elif args.op in {"add", "update"}:
        print("[after] " + json.dumps(_display(args.table, result), ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False))
    print(f"数据库：{database.DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
