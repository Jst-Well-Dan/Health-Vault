import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.backups import backup_dir  # noqa: E402


BACKUP_SUFFIXES = {".db", ".db-shm", ".db-wal"}


def _current_backup_dir() -> Path:
    return backup_dir().resolve()


def _backup_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in BACKUP_SUFFIXES and "before_restore" not in path.name
    ]


def _is_safe_backup_path(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
    except ValueError:
        return False
    return path.is_file() and path.suffix.lower() in BACKUP_SUFFIXES and "before_restore" not in path.name


def prune_old_backups(days: int, write: bool) -> dict:
    if days < 1:
        raise ValueError("days must be at least 1")

    directory = _current_backup_dir()
    cutoff = datetime.now() - timedelta(days=days)
    candidates = []
    for path in _backup_files(directory):
        modified_at = datetime.fromtimestamp(path.stat().st_mtime)
        if modified_at < cutoff:
            candidates.append((path, modified_at))

    deleted = []
    if write:
        for path, modified_at in candidates:
            if not _is_safe_backup_path(path, directory):
                raise ValueError(f"unsafe backup path: {path}")
            path.unlink()
            deleted.append({"path": str(path), "modified_at": modified_at.isoformat(timespec="seconds")})

    return {
        "ok": True,
        "mode": "write" if write else "dry-run",
        "backup_dir": str(directory),
        "days": days,
        "cutoff": cutoff.isoformat(timespec="seconds"),
        "matched": [
            {"path": str(path), "modified_at": modified_at.isoformat(timespec="seconds")}
            for path, modified_at in candidates
        ],
        "deleted": deleted,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete old SQLite backup files next to the active health database.")
    parser.add_argument("--days", type=int, default=7, help="Delete backup files older than this many days.")
    parser.add_argument("--write", action="store_true", help="Actually delete matching files. Omit for dry-run.")
    args = parser.parse_args()

    import json

    print(json.dumps(prune_old_backups(args.days, args.write), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
