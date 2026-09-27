from typing import Optional

from fastapi import APIRouter, HTTPException

from database import get_conn
from models import LabRecordCreate, LabUpdate
from routers.common import rows_to_dicts
from services.writes import (
    PayloadError,
    VisitMismatchError,
    create_lab_record,
    delete_lab_record,
    update_lab_record,
)


router = APIRouter(tags=["labs"])


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@router.get("/labs")
def list_labs(member: str, panel: Optional[str] = None, visit_id: Optional[int] = None) -> list[dict]:
    where = ["member_key = ?"]
    values: list = [member]
    if panel:
        where.append("panel = ?")
        values.append(panel)
    if visit_id is not None:
        where.append("visit_id = ?")
        values.append(visit_id)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM lab_results WHERE {' AND '.join(where)} ORDER BY date DESC, id DESC",
            values,
        ).fetchall()
        return rows_to_dicts(rows)


@router.get("/labs/available")
def available_labs(member: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT test_name, panel, unit, COUNT(*) AS count
            FROM lab_results
            WHERE member_key = ?
            GROUP BY test_name, panel, unit
            HAVING COUNT(*) >= 2
            ORDER BY test_name
            """,
            (member,),
        ).fetchall()
        return rows_to_dicts(rows)


@router.get("/labs/trend")
def lab_trend(member: str, test_name: str) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT date, value, unit, ref_low, ref_high, status, visit_id
            FROM lab_results
            WHERE member_key = ? AND test_name = ?
            ORDER BY date ASC, id ASC
            """,
            (member, test_name),
        ).fetchall()
    unit = rows[-1]["unit"] if rows else None
    ref_low = rows[-1]["ref_low"] if rows else None
    ref_high = rows[-1]["ref_high"] if rows else None
    points = [
        {
            "date": row["date"],
            "value": _to_float(row["value"]),
            "status": row["status"],
            "visit_id": row["visit_id"],
        }
        for row in rows
        if _to_float(row["value"]) is not None
    ]
    return {"test_name": test_name, "unit": unit, "ref_low": ref_low, "ref_high": ref_high, "points": points}


@router.post("/labs")
def create_lab(payload: LabRecordCreate) -> dict:
    try:
        return create_lab_record(**payload.model_dump())
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VisitMismatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/labs/{lab_id}")
def update_lab(lab_id: int, payload: LabUpdate) -> dict:
    try:
        return update_lab_record(lab_id, payload.model_dump(exclude_unset=True))
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VisitMismatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/labs/{lab_id}")
def delete_lab(lab_id: int) -> dict:
    try:
        return delete_lab_record(lab_id)
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
