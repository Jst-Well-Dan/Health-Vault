import json

from fastapi import APIRouter, HTTPException

from database import get_conn
from models import VisitCreate, VisitUpdate
from routers.common import bool_out, json_dumps, json_loads, require_row, rows_to_dicts


router = APIRouter(tags=["visits"])


def _visit(row) -> dict:
    item = dict(row)
    item["diagnosis"] = json_loads(item.get("diagnosis"))
    return item


def _med(row) -> dict:
    return bool_out(dict(row), "ongoing")


@router.get("/visits")
def list_visits(member: str, limit: int = 20, offset: int = 0) -> dict:
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM visits WHERE member_key = ?", (member,)).fetchone()["c"]
        rows = conn.execute(
            """
            SELECT * FROM visits
            WHERE member_key = ?
            ORDER BY date DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (member, limit, offset),
        ).fetchall()
        return {"total": total, "items": [_visit(row) for row in rows]}


@router.get("/visits/{visit_id}")
def get_visit(visit_id: int) -> dict:
    with get_conn() as conn:
        visit = _visit(require_row(conn.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()))
        labs = rows_to_dicts(conn.execute("SELECT * FROM lab_results WHERE visit_id = ? ORDER BY id", (visit_id,)).fetchall())
        meds = [_med(row) for row in conn.execute("SELECT * FROM meds WHERE visit_id = ? ORDER BY id", (visit_id,)).fetchall()]
        attachments = rows_to_dicts(
            conn.execute("SELECT * FROM attachments WHERE visit_id = ? ORDER BY date DESC, id DESC", (visit_id,)).fetchall()
        )
        return {"visit": visit, "labs": labs, "meds": meds, "attachments": attachments}


@router.post("/visits")
def create_visit(payload: VisitCreate) -> dict:
    with get_conn() as conn:
        require_row(conn.execute("SELECT key FROM members WHERE key = ?", (payload.member_key,)).fetchone(), "成员不存在")
        cur = conn.execute(
            """
            INSERT INTO visits
              (member_key, date, type, hospital, department, doctor, chief_complaint,
               severity, diagnosis, notes, note_full, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.member_key, payload.date, payload.type, payload.hospital,
                payload.department, payload.doctor, payload.chief_complaint,
                payload.severity, json_dumps(payload.diagnosis), payload.notes,
                payload.note_full, payload.source_file,
            ),
        )
        return _visit(conn.execute("SELECT * FROM visits WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.patch("/visits/{visit_id}")
def update_visit(visit_id: int, payload: VisitUpdate) -> dict:
    data = payload.model_dump(exclude_unset=True)
    with get_conn() as conn:
        require_row(conn.execute("SELECT id FROM visits WHERE id = ?", (visit_id,)).fetchone(), "就诊记录不存在")
        if data:
            if "diagnosis" in data:
                data["diagnosis"] = json_dumps(data["diagnosis"])
            conn.execute(
                f"UPDATE visits SET {', '.join(f'{field} = ?' for field in data)} WHERE id = ?",
                [*data.values(), visit_id],
            )
        return _visit(conn.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone())


@router.delete("/visits/{visit_id}")
def delete_visit(visit_id: int) -> dict:
    with get_conn() as conn:
        require_row(conn.execute("SELECT id FROM visits WHERE id = ?", (visit_id,)).fetchone(), "就诊记录不存在")
        counts = {
            "化验": conn.execute("SELECT COUNT(*) FROM lab_results WHERE visit_id = ?", (visit_id,)).fetchone()[0],
            "用药": conn.execute("SELECT COUNT(*) FROM meds WHERE visit_id = ?", (visit_id,)).fetchone()[0],
            "附件": conn.execute("SELECT COUNT(*) FROM attachments WHERE visit_id = ?", (visit_id,)).fetchone()[0],
        }
        reminder_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(reminders)").fetchall()
        }
        if "visit_id" in reminder_columns:
            counts["提醒"] = conn.execute("SELECT COUNT(*) FROM reminders WHERE visit_id = ?", (visit_id,)).fetchone()[0]
        if any(counts.values()):
            linked_text = "/".join(f"{count} 项{name}" for name, count in counts.items() if count)
            raise HTTPException(
                status_code=409,
                detail=f"就诊记录仍关联 {linked_text}，需先解除关联或分别处理",
            )
        conn.execute("DELETE FROM visits WHERE id = ?", (visit_id,))
    return {"ok": True, "id": visit_id}
