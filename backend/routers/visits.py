from fastapi import APIRouter, HTTPException

from database import get_conn
from models import VisitCreate, VisitUpdate
from routers.common import bool_out, json_loads, require_row, rows_to_dicts
from services.writes import LinkedRecordsError, PayloadError, create_visit_record, delete_visit_record, update_visit_record


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
    try:
        return create_visit_record(**payload.model_dump())
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/visits/{visit_id}")
def update_visit(visit_id: int, payload: VisitUpdate) -> dict:
    try:
        return update_visit_record(visit_id, payload.model_dump(exclude_unset=True))
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/visits/{visit_id}")
def delete_visit(visit_id: int) -> dict:
    try:
        return delete_visit_record(visit_id)
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LinkedRecordsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
