"""Restore one validated SQLite backup locally while the Web server is stopped."""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from database import DB_PATH
from services.backups import create_database_backup, validate_database_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="从本机备份恢复家庭健康档案数据库（不会恢复附件文件）")
    parser.add_argument("filename", help="data/backups 中的 .db 备份文件名")
    parser.add_argument("--confirm", action="store_true", help="确认已停止 Web 服务并执行恢复")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("恢复是破坏性操作：请先停止 Web 服务，核对备份后加 --confirm 重试。")

    metadata = validate_database_backup(args.filename)
    backup_path = DB_PATH.parent / "backups" / metadata["filename"]
    pre_restore = create_database_backup(prefix="health_prerestore")
    temp_path = DB_PATH.with_suffix(".restore.tmp")
    try:
        shutil.copy2(backup_path, temp_path)
        for suffix in ("-wal", "-shm"):
            Path(f"{DB_PATH}{suffix}").unlink(missing_ok=True)
        temp_path.replace(DB_PATH)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    print(f"已恢复：{metadata['filename']}\n恢复前备份：{pre_restore['backup_path']}\n数据库：{DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
