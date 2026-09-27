from fastapi import APIRouter, HTTPException

from database import get_conn
from models import WeightCreate
from routers.common import rows_to_dicts
from services.writes import PayloadError, create_weight_record, delete_weight_record


router = APIRouter(tags=["weight"])


@router.get("/weight")
def list_weight(member: str) -> list[dict]:
    with get_conn() as conn:
        return rows_to_dicts(
            conn.execute(
                "SELECT * FROM weight_log WHERE member_key = ? ORDER BY date ASC, id ASC",
                (member,),
            ).fetchall()
        )


@router.post("/weight")
def create_weight(payload: WeightCreate) -> dict:
    return create_weight_record(**payload.model_dump())


@router.delete("/weight/{weight_id}")
def delete_weight(weight_id: int) -> dict:
    try:
        return delete_weight_record(weight_id)
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
