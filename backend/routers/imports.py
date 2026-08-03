import base64
import json
import re
import shutil
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel, Field

import database
from database import get_conn
from routers.common import json_dumps, row_to_dict
from services.backups import create_database_backup


router = APIRouter(tags=["imports"])

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PREVIEW_PAGES = 8
ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class ReportVisit(BaseModel):
    date: str
    type: str = "体检"
    hospital: str | None = None
    department: str | None = None
    doctor: str | None = None
    chief_complaint: str | None = None
    severity: str | None = None
    diagnosis: list[str] = Field(default_factory=list)
    notes: str | None = None
    note_full: str | None = None


class ReportLab(BaseModel):
    panel: str
    test_name: str
    value: str | None = None
    unit: str | None = None
    ref_low: str | None = None
    ref_high: str | None = None
    status: str | None = "unknown"


class ReportImportCommit(BaseModel):
    source_id: str
    member_key: str
    visit: ReportVisit
    labs: list[ReportLab] = Field(default_factory=list)
    attachment_title: str | None = None
    attachment_tag: str = "体检报告"


def _data_dir() -> Path:
    return database.DB_PATH.parent.resolve()


def _staging_dir(source_id: str) -> Path:
    return _data_dir() / "imports" / ".staging" / source_id


def _safe_filename(value: str) -> str:
    name = Path(value).name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    return name


def _safe_part(value: str | None, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", (value or "").strip())
    cleaned = re.sub(r"\s+", "", cleaned).strip("._")
    return (cleaned or fallback)[:60]


def _image_preview(content: bytes) -> list[dict]:
    try:
        image = Image.open(BytesIO(content)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="无法读取图片文件") from exc
    image.thumbnail((1800, 1800))
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return [{"mime_type": "image/png", "data": base64.b64encode(output.getvalue()).decode("ascii")}]


def _pdf_preview(content: bytes) -> tuple[list[dict], str, int]:
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="无法读取 PDF 文件") from exc
    try:
        page_count = document.page_count
        if page_count > MAX_PREVIEW_PAGES:
            raise HTTPException(status_code=400, detail=f"当前最多支持解析 {MAX_PREVIEW_PAGES} 页的报告")
        images: list[dict] = []
        texts: list[str] = []
        for page in document:
            texts.append(page.get_text("text"))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            images.append({"mime_type": "image/png", "data": base64.b64encode(pixmap.tobytes("png")).decode("ascii")})
        return images, "\n".join(texts).strip(), page_count
    finally:
        document.close()


def stage_report(filename: str, content: bytes, content_type: str | None = None) -> dict:
    """Archive an upload in a private staging area and return safe vision inputs."""
    filename = _safe_filename(filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 PDF、PNG、JPG、WEBP 或 BMP 报告")
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="单份报告不能超过 20 MB")

    source_id = uuid4().hex
    folder = _staging_dir(source_id)
    folder.mkdir(parents=True, exist_ok=False)
    source_path = folder / filename
    source_path.write_bytes(content)
    metadata = {"filename": filename, "suffix": suffix, "content_type": content_type or ""}
    (folder / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    if suffix == ".pdf":
        images, text, page_count = _pdf_preview(content)
    else:
        images, text, page_count = _image_preview(content), "", 1
    return {
        "id": source_id,
        "filename": filename,
        "page_count": page_count,
        "text": text,
        "images": images,
    }


@router.post("/imports/stage")
async def stage_upload(file: UploadFile = File(...)) -> dict:
    content = await file.read(MAX_FILE_BYTES + 1)
    return stage_report(file.filename or "report", content, file.content_type)


def _load_staged_source(source_id: str) -> tuple[Path, dict]:
    if not re.fullmatch(r"[a-f0-9]{32}", source_id):
        raise HTTPException(status_code=400, detail="无效的导入会话")
    folder = _staging_dir(source_id)
    metadata_path = folder / "metadata.json"
    if not metadata_path.is_file():
        raise HTTPException(status_code=404, detail="导入会话不存在或已过期")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source_path = folder / _safe_filename(metadata.get("filename", ""))
    if not source_path.is_file():
        raise HTTPException(status_code=404, detail="暂存的报告文件不存在")
    return source_path, metadata


def _report_markdown(payload: ReportImportCommit, source_rel: str) -> str:
    visit = payload.visit
    lines = [
        f"# {visit.chief_complaint or '体检报告'}",
        "",
        f"- 日期：{visit.date}",
        f"- 机构：{visit.hospital or '未识别'}",
        f"- 原始报告：`{source_rel}`",
        "",
        "### 医生诊断",
        "；".join(visit.diagnosis) or "报告未列出明确诊断。",
        "",
        "### 诊疗意见",
        visit.notes or "请以原始报告为准。",
        "",
        "### 治疗方案说明",
        "报告中未提供具体用药或治疗方案。",
    ]
    if payload.labs:
        lines.extend(["", "### 检验指标", "", "| 项目 | 结果 | 单位 | 参考范围 | 状态 |", "| --- | --- | --- | --- | --- |"])
        for lab in payload.labs:
            reference = "–".join(item for item in (lab.ref_low, lab.ref_high) if item) or "–"
            lines.append(f"| {lab.test_name} | {lab.value or '–'} | {lab.unit or '–'} | {reference} | {lab.status or 'unknown'} |")
    return "\n".join(lines) + "\n"


def _backup_database() -> Path:
    return Path(create_database_backup(prefix="health")["backup_path"])


def _validate_commit(payload: ReportImportCommit) -> tuple[Path, dict, str]:
    try:
        datetime.strptime(payload.visit.date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="报告日期必须为 YYYY-MM-DD") from exc
    if payload.visit.severity not in {None, "严重", "一般", "轻微"}:
        raise HTTPException(status_code=400, detail="严重程度只能为严重、一般、轻微或留空")
    source_path, metadata = _load_staged_source(payload.source_id)
    with get_conn() as conn:
        member = conn.execute("SELECT name FROM members WHERE key = ?", (payload.member_key,)).fetchone()
    if not member:
        raise HTTPException(status_code=400, detail="成员不存在")
    return source_path, metadata, member["name"]


@router.post("/imports/dry-run")
def dry_run_report(payload: ReportImportCommit) -> dict:
    _source_path, metadata, member_name = _validate_commit(payload)
    return {
        "ok": True,
        "filename": metadata["filename"],
        "member_name": member_name,
        "visit_count": 1,
        "lab_count": len(payload.labs),
        "attachment_count": 1,
        "database_path": str(database.DB_PATH),
    }


@router.post("/imports/commit")
def commit_report(payload: ReportImportCommit) -> dict:
    source_path, metadata, member_name = _validate_commit(payload)
    date_compact = payload.visit.date.replace("-", "")
    org = _safe_part(payload.visit.hospital, "未知机构")
    item = _safe_part(payload.visit.chief_complaint, "体检报告")
    name = _safe_part(member_name, payload.member_key)
    suffix = metadata["suffix"]
    type_dir = "pdf" if suffix == ".pdf" else "images"
    report_dir = _data_dir() / "reports" / payload.member_key
    raw_dir = report_dir / type_dir
    markdown_dir = report_dir / "md"
    raw_dir.mkdir(parents=True, exist_ok=True)
    markdown_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{date_compact}_{org}_{item}_{name}"
    raw_path = raw_dir / f"{stem}{suffix}"
    if raw_path.exists():
        raw_path = raw_dir / f"{stem}_{payload.source_id[:6]}{suffix}"
    markdown_path = markdown_dir / f"{raw_path.stem}.md"

    # Preserve source and an auditable structured summary before the database transaction.
    shutil.copy2(source_path, raw_path)
    source_rel = raw_path.relative_to(_data_dir().parent).as_posix()
    markdown_rel = markdown_path.relative_to(_data_dir().parent).as_posix()
    markdown_path.write_text(_report_markdown(payload, source_rel), encoding="utf-8")
    backup_path = _backup_database()

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO visits (member_key, date, type, hospital, department, doctor, chief_complaint,
                                severity, diagnosis, notes, note_full, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.member_key, payload.visit.date, payload.visit.type, payload.visit.hospital,
                payload.visit.department, payload.visit.doctor, payload.visit.chief_complaint,
                payload.visit.severity, json_dumps(payload.visit.diagnosis), payload.visit.notes,
                payload.visit.note_full or _report_markdown(payload, source_rel), markdown_rel,
            ),
        )
        visit_id = cur.lastrowid
        for lab in payload.labs:
            conn.execute(
                """
                INSERT INTO lab_results (member_key, visit_id, date, panel, test_name, value, unit,
                                         ref_low, ref_high, status, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.member_key, visit_id, payload.visit.date, lab.panel, lab.test_name, lab.value,
                    lab.unit, lab.ref_low, lab.ref_high, lab.status, markdown_rel,
                ),
            )
        attachment = conn.execute(
            """
            INSERT INTO attachments (member_key, visit_id, date, title, org, tag, filename, file_path, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.member_key, visit_id, payload.visit.date,
                payload.attachment_title or payload.visit.chief_complaint or "体检报告",
                payload.visit.hospital, payload.attachment_tag, raw_path.name, source_rel,
                "由报告导入流程归档；结构化摘要见 source_file。",
            ),
        )
        visit = row_to_dict(conn.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone())

    shutil.rmtree(_staging_dir(payload.source_id), ignore_errors=True)
    return {
        "visit": visit,
        "visit_id": visit_id,
        "lab_count": len(payload.labs),
        "attachment_id": attachment.lastrowid,
        "database_path": str(database.DB_PATH),
        "backup_path": str(backup_path),
        "source_file": source_rel,
        "markdown_file": markdown_rel,
    }
