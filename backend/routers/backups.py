import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from services.backups import (
    MAX_BUNDLE_BYTES,
    MAX_IMPORT_BYTES,
    backup_info,
    create_database_backup,
    export_bundle_to_temp,
    import_bundle_zip,
    import_database_backup,
    prepare_database_restore,
    resolve_backup,
    validate_database_backup,
)


router = APIRouter(tags=["backups"])


class BackupSelection(BaseModel):
    filename: str


@router.get("/backups/info")
def get_backups_info() -> dict:
    return backup_info()


@router.post("/backups", status_code=201)
def create_backup() -> dict:
    return create_database_backup()


@router.get("/backups/download/{filename}")
def download_backup(filename: str) -> FileResponse:
    try:
        path = resolve_backup(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.post("/backups/import", status_code=200)
async def import_backup(file: UploadFile = File(...)) -> dict:
    content = await file.read(MAX_IMPORT_BYTES + 1)
    try:
        return await asyncio.to_thread(import_database_backup, content, file.filename or "imported.db")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/backups/export-bundle")
def export_bundle() -> FileResponse:
    """Build an on-demand migration zip (db + reports + settings + manifest)."""
    path, meta = export_bundle_to_temp()
    filename = f"health-vault-{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return FileResponse(
        path,
        filename=filename,
        media_type="application/zip",
        background=BackgroundTask(Path(path).unlink, missing_ok=True),
    )


@router.post("/backups/import-bundle", status_code=200)
async def import_bundle(file: UploadFile = File(...)) -> dict:
    content = await file.read(MAX_BUNDLE_BYTES + 1)
    try:
        return await asyncio.to_thread(import_bundle_zip, content, file.filename or "bundle.zip")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
