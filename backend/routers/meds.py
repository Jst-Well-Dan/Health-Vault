from fastapi import APIRouter, HTTPException

from database import get_conn
from models import MedCreate, MedUpdate
from routers.common import bool_out, row_to_dict, rows_to_dicts
from services.writes import PayloadError, create_med_record, delete_med_record, update_med_record


router = APIRouter(tags=["meds"])


def _med(row) -> dict:
    return bool_out(dict(row), "ongoing")


@router.get("/meds")
def list_meds(member: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM meds
            WHERE member_key = ?
            ORDER BY ongoing DESC, COALESCE(start_date, '') DESC, id DESC
            """,
            (member,),
        ).fetchall()
        return [_med(row) for row in rows]


@router.post("/meds")
def create_med(payload: MedCreate) -> dict:
    return create_med_record(**payload.model_dump())


@router.patch("/meds/{med_id}")
def update_med(med_id: int, payload: MedUpdate) -> dict:
    try:
        return update_med_record(med_id, payload.model_dump(exclude_unset=True))
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/meds/{med_id}")
def delete_med(med_id: int) -> dict:
    try:
        return delete_med_record(med_id)
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
