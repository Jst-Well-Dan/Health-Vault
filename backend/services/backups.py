import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import database


CORE_TABLES = {
    "members",
    "visits",
    "lab_results",
    "meds",
    "weight_log",
    "reminders",
    "attachments",
    "agent_change_log",
    "agent_messages",
}


def backup_dir() -> Path:
    """Return the fixed backups directory next to the active SQLite database."""
    return database.DB_PATH.parent / "backups"


def _backup_item(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "filename": path.name,
        "backup_path": str(path),
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def _safe_backup_metadata(path: Path, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    item = _backup_item(path)
    item.pop("backup_path", None)
    if schema is not None:
        item["schema"] = schema
        item["user_version"] = schema.get("user_version")
    return item


def list_database_backups(limit: int = 20) -> list[dict[str, Any]]:
    directory = backup_dir()
    if not directory.exists():
        return []
    limit = max(1, min(int(limit or 20), 100))
    files = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".db"]
    files.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return [_backup_item(path) for path in files[:limit]]


def backup_info(limit: int = 20) -> dict[str, Any]:
    directory = backup_dir()
    return {
        "database_path": str(database.DB_PATH),
        "backup_dir": str(directory),
        "exists": directory.exists(),
        "backups": list_database_backups(limit),
    }


def resolve_backup(filename: str) -> Path:
    if not filename or Path(filename).name != filename:
        raise ValueError("只能选择备份目录内的单一数据库文件名")
    raw = Path(filename)
    if raw.is_absolute() or any(part in {"", ".", ".."} for part in raw.parts) or len(raw.parts) != 1:
        raise ValueError("备份文件名不合法")
    if raw.suffix.lower() != ".db":
        raise ValueError("只能恢复 .db 备份文件")

    directory = backup_dir().resolve()
    path = (directory / filename).resolve()
    if path.parent != directory:
        raise ValueError("备份文件不在备份目录内")
    if not path.is_file():
        raise ValueError("备份文件不存在")
    return path


def _validate_sqlite_database(path: Path) -> dict[str, Any]:
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise ValueError("无法以只读方式打开备份数据库") from exc
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("备份数据库完整性校验失败")
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        tables = {row[0] for row in rows}
        missing = sorted(CORE_TABLES - tables)
        if missing:
            raise ValueError(f"备份不是完整的家庭健康档案数据库，缺少表：{', '.join(missing)}")
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        return {
            "integrity_check": integrity[0],
            "tables": sorted(CORE_TABLES),
            "user_version": user_version,
        }
    except sqlite3.DatabaseError as exc:
        raise ValueError("备份数据库损坏或不是 SQLite 数据库") from exc
    finally:
        conn.close()


def validate_database_backup(filename: str) -> dict[str, Any]:
    path = resolve_backup(filename)
    schema = _validate_sqlite_database(path)
    return _safe_backup_metadata(path, schema)


def create_database_backup(prefix: str = "health_manual") -> dict[str, Any]:
    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now()
    suffix = database.DB_PATH.suffix or ".db"
    filename = f"{prefix}_{created_at.strftime('%Y%m%d_%H%M%S_%f')}{suffix}"
    destination_path = directory / filename

    source = sqlite3.connect(database.DB_PATH)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    stat = destination_path.stat()
    return {
        "ok": True,
        "database_path": str(database.DB_PATH),
        "backup_dir": str(directory),
        "backup_path": str(destination_path),
        "filename": filename,
        "size_bytes": stat.st_size,
        "created_at": created_at.isoformat(timespec="microseconds"),
    }


def prepare_database_restore(filename: str) -> dict[str, Any]:
    selected = validate_database_backup(filename)
    pre_restore = create_database_backup(prefix="health_prerestore")
    return {
        "ok": True,
        "database_path": str(database.DB_PATH),
        "backup_dir": str(backup_dir()),
        "selected_backup": selected,
        "pre_restore_backup": pre_restore,
    }
