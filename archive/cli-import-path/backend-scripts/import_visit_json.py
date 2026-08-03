import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from database import DB_PATH, get_conn, init_db, is_mock_mode  # noqa: E402
from import_md import SEVERITY_VALUES, import_payload  # noqa: E402


def _load_payload(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_date(value: object, name: str) -> str:
    text = _require_string(value, name)
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD format") from exc
    return text


def _validate_optional_list(value: object, name: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _validate_payload_shape(payload: dict) -> None:
    visit = payload.get("visit")
    if not isinstance(visit, dict):
        raise ValueError("visit must be an object")

    _require_string(visit.get("member_key"), "visit.member_key")
    _validate_date(visit.get("date"), "visit.date")
    if visit.get("type") is not None:
        _require_string(visit.get("type"), "visit.type")

    if "severity" not in visit:
        raise ValueError("visit.severity must be present; use null only when evidence is insufficient")
    severity = visit.get("severity")
    if severity is not None and severity not in SEVERITY_VALUES:
        allowed = ", ".join(sorted(SEVERITY_VALUES))
        raise ValueError(f"visit.severity must be one of: {allowed}")

    if "diagnosis" not in visit:
        raise ValueError("visit.diagnosis must be present; use [] only when the source has no diagnosis or conclusion")
    diagnosis = visit.get("diagnosis", [])
    if not isinstance(diagnosis, list) or any(not isinstance(item, str) for item in diagnosis):
        raise ValueError("visit.diagnosis must be a list of strings")

    _require_string(visit.get("notes"), "visit.notes")
    _require_string(visit.get("note_full"), "visit.note_full")

    for index, lab in enumerate(_validate_optional_list(payload.get("labs", []), "labs")):
        if not isinstance(lab, dict):
            raise ValueError(f"labs[{index}] must be an object")
        _require_string(lab.get("panel"), f"labs[{index}].panel")
        _require_string(lab.get("test_name"), f"labs[{index}].test_name")

    for index, med in enumerate(_validate_optional_list(payload.get("meds", []), "meds")):
        if not isinstance(med, dict):
            raise ValueError(f"meds[{index}] must be an object")
        _require_string(med.get("name"), f"meds[{index}].name")

    for index, attachment in enumerate(_validate_optional_list(payload.get("attachments", []), "attachments")):
        if not isinstance(attachment, dict):
            raise ValueError(f"attachments[{index}] must be an object")
        _require_string(attachment.get("title"), f"attachments[{index}].title")
        if attachment.get("date") is not None:
            _validate_date(attachment.get("date"), f"attachments[{index}].date")


def _validate_member_exists(member_key: str) -> None:
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT key FROM members WHERE key = ?", (member_key,)).fetchone()
    if row is None:
        raise ValueError(f"member_key does not exist: {member_key}")


def _backup_database() -> Path | None:
    if is_mock_mode():
        return None

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = PROJECT_DIR / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{DB_PATH.stem}_{timestamp}{DB_PATH.suffix}"

    with sqlite3.connect(DB_PATH) as source:
        with sqlite3.connect(backup_path) as target:
            source.backup(target)

    return backup_path


def _counts(payload: dict) -> dict:
    return {
        "labs": len(payload.get("labs", [])),
        "meds": len(payload.get("meds", [])),
        "attachments": len(payload.get("attachments", [])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely import a visit JSON payload into SQLite.")
    parser.add_argument("--file", required=True, help="Path to a JSON payload file.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Validate only; do not write.")
    mode.add_argument("--write", action="store_true", help="Validate, back up the real database, then write.")
    args = parser.parse_args()

    payload_path = Path(args.file).resolve()
    payload = _load_payload(payload_path)
    _validate_payload_shape(payload)
    _validate_member_exists(payload["visit"]["member_key"])

    result = {
        "ok": True,
        "mode": "dry-run" if args.dry_run else "write",
        "db_path": str(DB_PATH),
        "file": str(payload_path),
        "member_key": payload["visit"]["member_key"],
        "visit_date": payload["visit"]["date"],
        "visit_type": payload["visit"].get("type"),
        "counts": _counts(payload),
    }

    if args.write:
        backup_path = _backup_database()
        visit_id = import_payload(payload)
        result["visit_id"] = visit_id
        result["backup_path"] = str(backup_path) if backup_path else None

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
