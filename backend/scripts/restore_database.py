"""Restore a .db snapshot or a .zip migration bundle while the Web server is stopped."""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from database import DB_PATH
from services.backups import create_database_backup, import_bundle_zip, validate_database_backup


def _restore_db_snapshot(filename: str) -> int:
    metadata = validate_database_backup(filename)
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


def _restore_bundle(path: Path) -> int:
    result = import_bundle_zip(path.read_bytes(), path.name)
    print(
        f"已导入迁移包：{result['imported_filename']}\n"
        f"恢复报告文件：{result['report_files_restored']} 个\n"
        f"恢复前备份：{result['pre_restore_backup']['backup_path']}\n"
        f"数据库：{result['database_path']}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="从本机 .db 快照或 .zip 迁移包恢复（不会删除本地多余报告）")
    parser.add_argument("filename", help="data/backups 中的 .db 快照文件名，或 .zip 迁移包路径")
    parser.add_argument("--confirm", action="store_true", help="确认已停止 Web 服务并执行恢复")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("恢复是破坏性操作：请先停止 Web 服务，核对备份后加 --confirm 重试。")

    candidate = Path(args.filename)
    if candidate.suffix.lower() == ".zip" and candidate.is_file():
        return _restore_bundle(candidate)
    return _restore_db_snapshot(candidate.name)


if __name__ == "__main__":
    raise SystemExit(main())
