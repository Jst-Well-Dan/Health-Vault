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

本脚本只是薄皮：校验/事务/复核都在 ``backend/services/writes.py``，
``routers`` 与本脚本共用同一套实现。
"""

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

import database  # noqa: E402
from services.backups import create_database_backup  # noqa: E402
from services.writes import (  # noqa: E402
    PayloadError,
    describe_plan,
    insert_bundle,
    load_payload,
    validate_bundle,
    verify_bundle,
)


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
        plan = validate_bundle(load_payload(args.file), args.member)
    except PayloadError as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        return 1

    if plan["duplicates"] and args.write and not args.allow_duplicate:
        print("校验失败：同一天已有就诊记录，确认不是重复后用 --allow-duplicate 重跑。", file=sys.stderr)
        print(describe_plan(plan), file=sys.stderr)
        return 1

    if not args.write:
        print("[dry-run] 未写入任何数据。\n" + describe_plan(plan))
        if args.json:
            print(json.dumps({"ok": True, "mode": "dry-run", "plan": {"member_key": plan["member_key"], "date": plan["date"],
                                                                      "labs": len(plan["labs"]), "meds": len(plan["meds"]),
                                                                      "attachments": len(plan["attachments"]),
                                                                      "duplicates": plan["duplicates"]}}, ensure_ascii=False))
        return 0

    backup = create_database_backup(prefix="health")
    try:
        inserted = insert_bundle(plan)
    except Exception as exc:  # 事务失败：给出可读原因，数据未落库
        print(f"写入失败（未提交）：{exc}\n已创建的备份：{backup['backup_path']}", file=sys.stderr)
        return 1

    result = verify_bundle(inserted["visit_id"], plan)
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
