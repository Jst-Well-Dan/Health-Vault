import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from database import get_conn, init_db  # noqa: E402
from path_utils import project_relative_path  # noqa: E402

SEVERITY_VALUES = {"严重", "轻微", "一般"}


def _json_list(value) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _severity(value: str | None) -> str | None:
    if not value:
        return None
    if value not in SEVERITY_VALUES:
        raise ValueError(f"severity must be one of {sorted(SEVERITY_VALUES)}, got {value!r}")
    return value


def _visit_type(visit: dict) -> str:
    value = visit.get("type")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "体检" if "体检" in str(visit.get("chief_complaint") or "") else "就医"


def import_payload(payload: dict) -> int:
    visit = payload["visit"]
    visit_source_file = project_relative_path(visit.get("source_file"))
    labs = payload.get("labs", [])
    meds = payload.get("meds", [])
    attachments = payload.get("attachments", [])

    init_db()
    with get_conn() as conn:
        try:
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

            for lab in labs:
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

            for med in meds:
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

            for attachment in attachments:
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
        except Exception:
            conn.rollback()
            raise

    return visit_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Import parsed medical report JSON into SQLite.")
    parser.add_argument("--data", required=True, help="JSON payload with visit, labs, meds and attachments.")
    args = parser.parse_args()
    visit_id = import_payload(json.loads(args.data))
    print(json.dumps({"ok": True, "visit_id": visit_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
