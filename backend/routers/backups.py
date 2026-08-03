from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.backups import backup_info, create_database_backup, prepare_database_restore, validate_database_backup


router = APIRouter(tags=["backups"])


class BackupSelection(BaseModel):
    filename: str


@router.get("/backups/info")
def get_backups_info() -> dict:
    return backup_info()


@router.post("/backups", status_code=201)
def create_backup() -> dict:
    return create_database_backup()


@router.post("/backups/validate")
def validate_backup(payload: BackupSelection) -> dict:
    try:
        return validate_database_backup(payload.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backups/prepare-restore")
def prepare_restore(payload: BackupSelection) -> dict:
    try:
        return prepare_database_restore(payload.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
