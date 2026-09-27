from typing import Optional

from fastapi import APIRouter, HTTPException

from database import get_conn
from models import PetCareLogCreate, PetCareLogUpdate
from routers.common import rows_to_dicts
from services.writes import (
    PayloadError,
    ValidationError,
    create_care_log_record,
    delete_care_log_record,
    update_care_log_record,
)


router = APIRouter(tags=["pet-care"])


@router.get("/pet-care")
def list_care_logs(member: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM pet_care_logs"
    values: list = []
    if member:
        sql += " WHERE member_key = ?"
        values.append(member)
    sql += " ORDER BY date ASC, id ASC"
    with get_conn() as conn:
        return rows_to_dicts(conn.execute(sql, values).fetchall())


@router.post("/pet-care")
def create_care_log(payload: PetCareLogCreate) -> dict:
    try:
        return create_care_log_record(**payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/pet-care/{log_id}")
def update_care_log(log_id: int, payload: PetCareLogUpdate) -> dict:
    try:
        return update_care_log_record(log_id, payload.model_dump(exclude_unset=True))
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/pet-care/{log_id}")
def delete_care_log(log_id: int) -> dict:
    try:
        return delete_care_log_record(log_id)
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
