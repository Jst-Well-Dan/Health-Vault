from typing import Optional
from pathlib import Path

import database
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from database import get_conn
from models import AttachmentRecordCreate, AttachmentUpdate
from path_utils import resolve_project_data_path
from routers.common import require_row, row_to_dict, rows_to_dicts
from services.writes import (
    PayloadError,
    VisitMismatchError,
    create_attachment_record,
    delete_attachment_record,
    update_attachment_record,
)


router = APIRouter(tags=["attachments"])


def _resolve_attachment_path(file_path: str | None) -> Path:
    if not file_path:
        raise HTTPException(status_code=404, detail="附件路径未记录")

    candidates: list[Path] = []
    try:
        candidates.append(resolve_project_data_path(file_path))
    except ValueError:
        pass

    raw = Path(file_path)
    data_root = database.DB_PATH.parent.resolve()
    if raw.is_absolute():
        resolved_raw = raw.resolve()
        if data_root in [resolved_raw, *resolved_raw.parents]:
            candidates.append(resolved_raw)
    else:
        candidates.append((data_root.parent / raw).resolve())
        candidates.append((data_root / raw).resolve())

    for resolved in candidates:
        if data_root not in [resolved, *resolved.parents]:
            continue
        if resolved.is_file():
            return resolved
    raise HTTPException(status_code=404, detail="附件文件不存在")


def _parse_visit_id(value: str | int | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="visit_id 必须是数字") from exc


def _validate_member_and_visit(member_key: str, visit_id: int | None) -> None:
    with get_conn() as conn:
        require_row(conn.execute("SELECT key FROM members WHERE key = ?", (member_key,)).fetchone(), "成员不存在")
        if visit_id is not None:
            visit = require_row(
                conn.execute("SELECT member_key FROM visits WHERE id = ?", (visit_id,)).fetchone(),
                "关联就诊记录不存在",
            )
            if visit["member_key"] != member_key:
                raise HTTPException(status_code=422, detail="关联就诊记录不属于当前成员")


def _attachment(attachment_id: int) -> dict:
    with get_conn() as conn:
        return row_to_dict(require_row(
            conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone(),
            "附件不存在",
        ))


@router.get("/attachments")
def list_attachments(member: str) -> list[dict]:
    with get_conn() as conn:
        return rows_to_dicts(
            conn.execute(
                "SELECT * FROM attachments WHERE member_key = ? ORDER BY date DESC, id DESC",
                (member,),
            ).fetchall()
        )


@router.get("/attachments/recent")
def recent_attachments(limit: int = 8) -> list[dict]:
    limit = max(1, min(limit, 50))
    with get_conn() as conn:
        return rows_to_dicts(
            conn.execute(
                "SELECT * FROM attachments ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        )


@router.get("/attachments/{attachment_id}/file")
def attachment_file(attachment_id: int, download: bool = False) -> FileResponse:
    attachment = _attachment(attachment_id)
    path = _resolve_attachment_path(attachment.get("file_path"))
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path,
        filename=attachment.get("filename") or path.name,
        content_disposition_type=disposition,
    )


@router.get("/attachments/{attachment_id}/text")
def attachment_text(attachment_id: int) -> PlainTextResponse:
    attachment = _attachment(attachment_id)
    path = _resolve_attachment_path(attachment.get("file_path"))
    if path.suffix.lower() not in {".md", ".txt", ".csv", ".json"}:
        raise HTTPException(status_code=415, detail="该附件不是可文本预览的文件")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@router.post("/attachments")
def create_attachment(payload: AttachmentRecordCreate) -> dict:
    file_path = payload.file_path
    if file_path:
        try:
            file_path = str(resolve_project_data_path(file_path).relative_to(Path(__file__).resolve().parents[2])).replace("\\", "/")
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    return create_attachment_record(
        member_key=payload.member_key, visit_id=payload.visit_id, date=payload.date,
        title=payload.title, org=payload.org, tag=payload.tag, filename=payload.filename,
        file_path=file_path, notes=payload.notes,
    )


@router.patch("/attachments/{attachment_id}")
def update_attachment(attachment_id: int, payload: AttachmentUpdate) -> dict:
    data = payload.model_dump(exclude_unset=True)
    if data.get("file_path"):
        try:
            data["file_path"] = str(resolve_project_data_path(data["file_path"]).relative_to(Path(__file__).resolve().parents[2])).replace("\\", "/")
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        return update_attachment_record(attachment_id, data)
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VisitMismatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _delete_file_candidate(file_path: str | None) -> Path | None:
    if not file_path:
        return None
    try:
        return _resolve_attachment_path(file_path)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise

    raw = Path(file_path)
    data_root = database.DB_PATH.parent.resolve()
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw.resolve())
    else:
        candidates.append((data_root.parent / raw).resolve())
        candidates.append((data_root / raw).resolve())

    for candidate in candidates:
        if data_root in [candidate, *candidate.parents]:
            return None
    raise HTTPException(status_code=403, detail="附件路径不在允许目录内，已取消删除文件")


@router.delete("/attachments/{attachment_id}")
def delete_attachment(attachment_id: int, delete_file: bool = False) -> dict:
    file_path: Path | None = None
    warning = None
    if delete_file:
        attachment = _attachment(attachment_id)
        file_path = _delete_file_candidate(attachment.get("file_path"))
        if attachment.get("file_path") and file_path is None:
            warning = "附件元数据已删除；原文件不存在或已被移走。"

    try:
        delete_attachment_record(attachment_id)
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    file_deleted = False
    if delete_file and file_path is not None:
        try:
            file_path.unlink()
            file_deleted = True
        except FileNotFoundError:
            warning = "附件元数据已删除；原文件不存在或已被移走。"
        except OSError as exc:
            warning = f"附件元数据已删除；原文件删除失败，请手动核对：{exc}"
    return {"ok": True, "file_deleted": file_deleted, **({"warning": warning} if warning else {})}
