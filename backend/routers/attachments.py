import re
from typing import Optional
from pathlib import Path
from uuid import uuid4

import database
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from database import get_conn
from models import AttachmentRecordCreate, AttachmentUpdate
from path_utils import resolve_project_data_path
from routers.common import require_row, row_to_dict, rows_to_dicts


router = APIRouter(tags=["attachments"])

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
ALLOWED_ATTACHMENT_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif",
    ".txt", ".md", ".csv", ".json", ".doc", ".docx", ".xls", ".xlsx",
}
SAFE_PART_RE = re.compile(r'[\\/:*?"<>|\r\n]+')


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


def _safe_filename(value: str | None) -> str:
    name = Path(value or "").name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_ATTACHMENT_SUFFIXES:
        raise HTTPException(status_code=400, detail="不支持的附件文件类型")
    stem = Path(name).stem.strip() or "attachment"
    safe_stem = re.sub(r"\s+", "_", SAFE_PART_RE.sub("_", stem)).strip("._") or "attachment"
    return f"{safe_stem[:80]}{suffix}"


def _safe_member_dir(member_key: str) -> str:
    safe = re.sub(r"\s+", "_", SAFE_PART_RE.sub("_", str(member_key or "").strip())).strip("._")
    return (safe or "member")[:80]


def _attachment_storage_dir(member_key: str) -> Path:
    return database.DB_PATH.parent.resolve() / "attachments" / _safe_member_dir(member_key)


def _stored_file_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(database.DB_PATH.parent.parent.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


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


def _insert_attachment_row(payload: dict) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO attachments
              (member_key, visit_id, date, title, org, tag, filename, file_path, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["member_key"], payload.get("visit_id"), payload["date"], payload["title"],
                payload.get("org"), payload.get("tag"), payload.get("filename"), payload.get("file_path"), payload.get("notes"),
            ),
        )
        return row_to_dict(conn.execute("SELECT * FROM attachments WHERE id = ?", (cur.lastrowid,)).fetchone())


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


@router.post("/attachments/upload")
async def upload_attachment(
    member_key: str = Form(...),
    date: str = Form(...),
    title: str = Form(...),
    org: Optional[str] = Form(None),
    tag: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    visit_id: Optional[str] = Form(None),
    file: UploadFile = File(...),
) -> dict:
    member_key = member_key.strip()
    title = title.strip()
    date = date.strip()
    if not member_key:
        raise HTTPException(status_code=422, detail="member_key 不能为空")
    if not title:
        raise HTTPException(status_code=422, detail="附件标题不能为空")
    if not date:
        raise HTTPException(status_code=422, detail="附件日期不能为空")

    parsed_visit_id = _parse_visit_id(visit_id)
    _validate_member_and_visit(member_key, parsed_visit_id)

    filename = _safe_filename(file.filename)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="附件大小不能超过 20MB")

    storage_dir = _attachment_storage_dir(member_key)
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"{uuid4().hex[:12]}_{filename}"
    stored_path.write_bytes(content)

    try:
        return _insert_attachment_row({
            "member_key": member_key,
            "visit_id": parsed_visit_id,
            "date": date,
            "title": title,
            "org": org,
            "tag": tag,
            "filename": filename,
            "file_path": _stored_file_path(stored_path),
            "notes": notes,
        })
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise


@router.post("/attachments")
def create_attachment(payload: AttachmentRecordCreate) -> dict:
    file_path = payload.file_path
    if file_path:
        try:
            file_path = str(resolve_project_data_path(file_path).relative_to(Path(__file__).resolve().parents[2])).replace("\\", "/")
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    data = payload.model_dump()
    data["file_path"] = file_path
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO attachments
              (member_key, visit_id, date, title, org, tag, filename, file_path, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.member_key, payload.visit_id, payload.date, payload.title,
                payload.org, payload.tag, payload.filename, file_path, payload.notes,
            ),
        )
        return row_to_dict(conn.execute("SELECT * FROM attachments WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.patch("/attachments/{attachment_id}")
def update_attachment(attachment_id: int, payload: AttachmentUpdate) -> dict:
    allowed_fields = {"visit_id", "date", "title", "org", "tag", "file_path", "notes"}
    data = {key: value for key, value in payload.model_dump(exclude_unset=True).items() if key in allowed_fields}
    if data.get("file_path"):
        try:
            data["file_path"] = str(resolve_project_data_path(data["file_path"]).relative_to(Path(__file__).resolve().parents[2])).replace("\\", "/")
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    with get_conn() as conn:
        attachment = require_row(
            conn.execute("SELECT member_key FROM attachments WHERE id = ?", (attachment_id,)).fetchone(),
            "附件不存在",
        )
        if data.get("visit_id") is not None:
            visit = require_row(
                conn.execute("SELECT member_key FROM visits WHERE id = ?", (data["visit_id"],)).fetchone(),
                "关联就诊记录不存在",
            )
            if visit["member_key"] != attachment["member_key"]:
                raise HTTPException(status_code=422, detail="关联就诊记录不属于当前成员")
        if data:
            conn.execute(
                f"UPDATE attachments SET {', '.join(f'{field} = ?' for field in data)} WHERE id = ?",
                [*data.values(), attachment_id],
            )
        return row_to_dict(conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone())


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

    with get_conn() as conn:
        require_row(conn.execute("SELECT id FROM attachments WHERE id = ?", (attachment_id,)).fetchone(), "附件不存在")
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))

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
