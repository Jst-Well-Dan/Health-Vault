import hashlib
import io
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import database
from database import init_db


MAX_IMPORT_BYTES = 200 * 1024 * 1024

CORE_TABLES = {
    "members",
    "visits",
    "lab_results",
    "meds",
    "weight_log",
    "pet_care_logs",
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


def _checkpoint_active_database() -> None:
    """Flush and remove WAL/SHM sidecars so the database file can be replaced."""
    conn = sqlite3.connect(database.DB_PATH)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    for sidecar in (Path(str(database.DB_PATH) + "-wal"), Path(str(database.DB_PATH) + "-shm")):
        try:
            sidecar.unlink(missing_ok=True)
        except OSError:
            pass


def import_database_backup(content: bytes, original_name: str) -> dict[str, Any]:
    """Validate an uploaded .db file and switch the active database to it.

    The current database is backed up first; the uploaded file is only
    installed after full validation. Failures never touch the active database.
    """
    if not content:
        raise ValueError("上传的数据库文件为空")
    if len(content) > MAX_IMPORT_BYTES:
        raise ValueError("上传的数据库文件不能超过 200 MB")
    name = Path(original_name or "imported.db").name.strip()
    if not name or Path(name).suffix.lower() != ".db":
        raise ValueError("只能导入 .db 数据库文件")

    with tempfile.NamedTemporaryFile(prefix="health_import_", suffix=".db", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        # Full validation before touching anything.
        _validate_sqlite_database(tmp_path)
        pre_restore = create_database_backup(prefix="health_prerestore")
        _checkpoint_active_database()

        database.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        staged = database.DB_PATH.with_name(f".health_import_{database.DB_PATH.name}.tmp")
        shutil.copyfile(tmp_path, staged)
        try:
            # os.replace fails with a file lock on Windows even when the
            # target is not held open; remove + rename avoids that.
            database.DB_PATH.unlink()
            os.rename(staged, database.DB_PATH)
        except OSError:
            if staged.exists() and not database.DB_PATH.exists():
                os.rename(staged, database.DB_PATH)
            raise

        # Apply the same schema migrations a fresh install would, so older
        # exported databases gain any missing columns/tables.
        init_db()
        schema = _validate_sqlite_database(database.DB_PATH)
        return {
            "ok": True,
            "database_path": str(database.DB_PATH),
            "imported_filename": name,
            "pre_restore_backup": pre_restore,
            "schema": schema,
            "restart_required": True,
        }
    finally:
        tmp_path.unlink(missing_ok=True)


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


BUNDLE_VERSION = 1
MAX_BUNDLE_BYTES = 1024 * 1024 * 1024
SNAPSHOT_KEEP_DAYS = 14
SNAPSHOT_KEEP_MINIMUM = 3


def _data_dir() -> Path:
    return database.DB_PATH.parent


def _reports_dir() -> Path:
    return _data_dir() / "reports"


def _settings_path() -> Path:
    return _data_dir() / "settings.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_active_db_to(destination: Path) -> None:
    """Copy the live database via the SQLite backup API (safe while running)."""
    source = sqlite3.connect(database.DB_PATH)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def build_bundle_zip(destination: Path) -> dict[str, Any]:
    """Write an on-demand migration bundle: health.db + reports/ + settings + manifest.

    The zip is built only when the user clicks export; per-write automatic
    backups stay as tiny .db snapshots and never produce zips.
    """
    created_at = datetime.now()
    data_dir = _data_dir()
    reports_dir = _reports_dir()
    settings_path = _settings_path()
    with tempfile.NamedTemporaryFile(prefix="health_bundle_db_", suffix=".db", delete=False) as tmp:
        tmp_db = Path(tmp.name)
    try:
        _snapshot_active_db_to(tmp_db)
        db_sha = _sha256_file(tmp_db)
        db_size = tmp_db.stat().st_size
        entries: list[dict[str, Any]] = []
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(tmp_db, "health.db")
            if reports_dir.is_dir():
                for path in sorted(reports_dir.rglob("*")):
                    if path.is_file():
                        relative = path.relative_to(data_dir).as_posix()
                        archive.write(path, relative)
                        entries.append({
                            "path": relative,
                            "size_bytes": path.stat().st_size,
                            "sha256": _sha256_file(path),
                        })
            settings_included = settings_path.is_file()
            if settings_included:
                archive.write(settings_path, "settings.json")
            manifest = {
                "bundle_version": BUNDLE_VERSION,
                "created_at": created_at.isoformat(timespec="seconds"),
                "database": {"path": "health.db", "size_bytes": db_size, "sha256": db_sha},
                "settings_included": settings_included,
                "report_files": entries,
                "report_file_count": len(entries),
            }
            archive.writestr("manifest.json", __import__("json").dumps(manifest, ensure_ascii=False, indent=2))
    finally:
        tmp_db.unlink(missing_ok=True)
    stat = destination.stat()
    return {
        "ok": True,
        "bundle_path": str(destination),
        "size_bytes": stat.st_size,
        "created_at": created_at.isoformat(timespec="seconds"),
        "database_sha256": db_sha,
        "report_file_count": len(entries),
        "settings_included": settings_path.is_file(),
    }


def export_bundle_to_temp() -> tuple[Path, dict[str, Any]]:
    """Build a bundle zip in the OS temp dir; the caller must delete it."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = Path(tempfile.gettempdir()) / f"health-vault-{stamp}.zip"
    meta = build_bundle_zip(destination)
    return destination, meta


def _assert_safe_zip_member(name: str) -> Path:
    pure = Path(name)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"备份包内含非法路径：{name}")
    return pure


def import_bundle_zip(content: bytes, original_name: str) -> dict[str, Any]:
    """Validate a bundle zip and migrate db + reports + settings in one go.

    Reports merge by overwrite; local extra files are never deleted, so a
    bad bundle cannot destroy reports that the db does not reference.
    """
    if not content:
        raise ValueError("上传的备份包为空")
    if len(content) > MAX_BUNDLE_BYTES:
        raise ValueError("上传的备份包不能超过 1 GB")
    name = Path(original_name or "bundle.zip").name.strip()
    if not name or Path(name).suffix.lower() != ".zip":
        raise ValueError("只能导入 .zip 备份包（用设置页导出的文件）")
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise ValueError("备份包损坏或不是 zip 文件")
    with tempfile.NamedTemporaryFile(prefix="health_bundle_", suffix=".zip", delete=False) as tmp:
        tmp.write(content)
        bundle_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            members = archive.namelist()
            if "health.db" not in members:
                raise ValueError("备份包缺少 health.db，不是有效的迁移包")
            for member in members:
                _assert_safe_zip_member(member)
            db_bytes = archive.read("health.db")
            try:
                manifest = __import__("json").loads(archive.read("manifest.json").decode("utf-8")) if "manifest.json" in members else None
            except ValueError as exc:
                raise ValueError("备份包的 manifest.json 已损坏") from exc
        with tempfile.NamedTemporaryFile(prefix="health_bundle_db_", suffix=".db", delete=False) as tmp_db:
            tmp_db.write(db_bytes)
            staged_db = Path(tmp_db.name)
        try:
            _validate_sqlite_database(staged_db)
        except ValueError:
            staged_db.unlink(missing_ok=True)
            raise
        pre_restore = create_database_backup(prefix="health_prerestore")
        settings_path = _settings_path()
        settings_backup = None
        if settings_path.is_file():
            settings_backup = _data_dir() / f"settings.prerestore.{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
            shutil.copy2(settings_path, settings_backup)
        _checkpoint_active_database()
        _data_dir().mkdir(parents=True, exist_ok=True)
        staged = database.DB_PATH.with_name(f".health_import_{database.DB_PATH.name}.tmp")
        shutil.copyfile(staged_db, staged)
        try:
            database.DB_PATH.unlink()
            os.rename(staged, database.DB_PATH)
        except OSError:
            if staged.exists() and not database.DB_PATH.exists():
                os.rename(staged, database.DB_PATH)
            raise
        finally:
            staged_db.unlink(missing_ok=True)
        report_count = 0
        with zipfile.ZipFile(bundle_path) as archive:
            for member in archive.namelist():
                if member in {"health.db", "manifest.json"} or member.endswith("/"):
                    continue
                if not (member == "settings.json" or member.startswith("reports/")):
                    continue
                target = (_data_dir() / _assert_safe_zip_member(member))
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
                if member.startswith("reports/"):
                    report_count += 1
        init_db()
        schema = _validate_sqlite_database(database.DB_PATH)
        return {
            "ok": True,
            "database_path": str(database.DB_PATH),
            "imported_filename": name,
            "pre_restore_backup": pre_restore,
            "settings_backup": str(settings_backup) if settings_backup else None,
            "report_files_restored": report_count,
            "manifest": manifest,
            "schema": schema,
            "restart_required": True,
        }
    finally:
        bundle_path.unlink(missing_ok=True)


def prune_old_snapshots(days: int = SNAPSHOT_KEEP_DAYS) -> dict[str, Any]:
    """Delete .db snapshots older than `days`, always keeping the newest few."""
    if days < 1:
        raise ValueError("days must be at least 1")
    directory = backup_dir()
    if not directory.exists():
        return {"ok": True, "deleted": [], "kept": 0}
    files = sorted(
        [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".db"],
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    always_keep = {p.name for p in files[:SNAPSHOT_KEEP_MINIMUM]}
    cutoff = datetime.now().timestamp() - days * 86400
    deleted: list[str] = []
    for path in files:
        if path.name in always_keep:
            continue
        if path.stat().st_mtime < cutoff:
            path.unlink()
            deleted.append(path.name)
    return {"ok": True, "deleted": deleted, "kept": len(files) - len(deleted), "days": days}
