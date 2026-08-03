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
from import_md import SEVERITY_VALUES, _json_list, _severity, _visit_type  # noqa: E402
from import_visit_json import (  # noqa: E402
    _load_payload,
    _validate_member_exists,
    _validate_payload_shape,
)
from path_utils import project_relative_path  # noqa: E402


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


def _insert_payload(conn: sqlite3.Connection, payload: dict) -> int:
    visit = payload["visit"]
    visit_source_file = project_relative_path(visit.get("source_file"))
    cur = conn.execute(
        """
        INSERT INTO visits
          (member_key, date, type, hospital, department, doctor, chief_complaint,
           severity, diagnosis, notes, note_full, source_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            visit["member_key"],
            visit["date"],
            _visit_type(visit),
            visit.get("hospital"),
            visit.get("department"),
            visit.get("doctor"),
            visit.get("chief_complaint"),
            _severity(visit.get("severity")),
            _json_list(visit.get("diagnosis")),
            visit.get("notes"),
            visit.get("note_full"),
            visit_source_file,
        ),
    )
    visit_id = cur.lastrowid

    for lab in payload.get("labs", []):
        conn.execute(
            """
            INSERT INTO lab_results
              (member_key, visit_id, date, panel, test_name, value, unit,
               ref_low, ref_high, status, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                visit["member_key"],
                visit_id,
                visit["date"],
                lab["panel"],
                lab["test_name"],
                lab.get("value"),
                lab.get("unit"),
                lab.get("ref_low"),
                lab.get("ref_high"),
                lab.get("status"),
                project_relative_path(lab.get("source_file") or visit.get("source_file")),
            ),
        )

    for med in payload.get("meds", []):
        conn.execute(
            """
            INSERT INTO meds
              (member_key, visit_id, name, dose, freq, route, start_date,
               end_date, ongoing, category, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                visit["member_key"],
                visit_id,
                med["name"],
                med.get("dose"),
                med.get("freq"),
                med.get("route"),
                med.get("start_date"),
                med.get("end_date"),
                1 if med.get("ongoing") else 0,
                med.get("category"),
                med.get("notes"),
            ),
        )

    for attachment in payload.get("attachments", []):
        conn.execute(
            """
            INSERT INTO attachments
              (member_key, visit_id, date, title, org, tag, filename, file_path, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                visit["member_key"],
                visit_id,
                attachment.get("date") or visit["date"],
                attachment["title"],
                attachment.get("org"),
                attachment.get("tag"),
                attachment.get("filename"),
                project_relative_path(attachment.get("file_path")),
                attachment.get("notes"),
            ),
        )

    return int(visit_id)


def _delete_old(conn: sqlite3.Connection, visit_ids: list[int]) -> dict[str, int]:
    if not visit_ids:
        return {"attachments": 0, "meds": 0, "labs": 0, "visits": 0}

    placeholders = ",".join("?" for _ in visit_ids)
    counts = {}
    counts["attachments"] = conn.execute(
        f"DELETE FROM attachments WHERE visit_id IN ({placeholders})", visit_ids
    ).rowcount
    counts["meds"] = conn.execute(f"DELETE FROM meds WHERE visit_id IN ({placeholders})", visit_ids).rowcount
    counts["labs"] = conn.execute(f"DELETE FROM lab_results WHERE visit_id IN ({placeholders})", visit_ids).rowcount
    counts["visits"] = conn.execute(f"DELETE FROM visits WHERE id IN ({placeholders})", visit_ids).rowcount
    return counts


def _counts(payload: dict) -> dict:
    return {
        "labs": len(payload.get("labs", [])),
        "meds": len(payload.get("meds", [])),
        "attachments": len(payload.get("attachments", [])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace existing visits with one or more visit JSON payloads.")
    parser.add_argument("--delete-visit-id", action="append", type=int, default=[], help="Existing visit id to delete.")
    parser.add_argument("--file", action="append", required=True, help="JSON payload file to import.")
    parser.add_argument("--write", action="store_true", required=True, help="Required explicit write flag.")
    args = parser.parse_args()

    payloads = []
    for file in args.file:
        path = Path(file).resolve()
        payload = _load_payload(path)
        _validate_payload_shape(payload)
        _validate_member_exists(payload["visit"]["member_key"])
        payloads.append((path, payload))

    init_db()
    backup_path = _backup_database()
    with get_conn() as conn:
        deleted = _delete_old(conn, args.delete_visit_id)
        inserted = []
        for path, payload in payloads:
            visit_id = _insert_payload(conn, payload)
            inserted.append({"file": str(path), "visit_id": visit_id, "counts": _counts(payload)})

    print(
        json.dumps(
            {
                "ok": True,
                "db_path": str(DB_PATH),
                "backup_path": str(backup_path) if backup_path else None,
                "deleted_visit_ids": args.delete_visit_id,
                "deleted_counts": deleted,
                "inserted": inserted,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
