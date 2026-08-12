import asyncio
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

import database
from database import get_conn
from routers.common import json_dumps, row_to_dict
from services.backups import create_database_backup
from services.mineru import SecureStorageError, command_path, extraction_env, resolved_mode


router = APIRouter(tags=["imports"])

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_REPORT_PAGES = 8
MINERU_FLASH_MAX_BYTES = 10 * 1024 * 1024
MINERU_TIMEOUT_SECONDS = 900
MINERU_PROCESS_TIMEOUT_SECONDS = MINERU_TIMEOUT_SECONDS + 30
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


def _pdf_page_count(content: bytes) -> int:
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="无法读取 PDF 文件") from exc
    try:
        if document.page_count > MAX_REPORT_PAGES:
            raise HTTPException(status_code=400, detail=f"当前最多支持解析 {MAX_REPORT_PAGES} 页的报告")
        return document.page_count
    finally:
        document.close()


def _mineru_command() -> str:
    command = command_path()
    if command:
        return command
    if os.getenv("HEALTH_MINERU_OPEN_API_CLI", "").strip():
        raise HTTPException(status_code=503, detail="HEALTH_MINERU_OPEN_API_CLI 指向的 MinerU CLI 不可用")
    raise HTTPException(status_code=503, detail="未找到 mineru-open-api CLI；请安装 MinerU OpenAPI CLI 后重试")


def _convert_with_mineru(source_path: Path) -> str:
    """Convert one private report to Markdown through MinerU OpenAPI CLI."""
    command = _mineru_command()
    mode = resolved_mode()
    if mode not in {"flash", "extract"}:
        raise HTTPException(status_code=500, detail="HEALTH_MINERU_MODE 只能为 flash 或 extract")
    if mode == "flash" and source_path.stat().st_size > MINERU_FLASH_MAX_BYTES:
        raise HTTPException(status_code=422, detail="报告超过 MinerU flash-extract 的 10 MB 限制；请配置 Token 并设置 HEALTH_MINERU_MODE=extract")

    subcommand = "flash-extract" if mode == "flash" else "extract"
    try:
        env = extraction_env()
    except SecureStorageError as exc:
        raise HTTPException(status_code=503, detail="无法访问 MinerU Token 的系统凭据库") from exc
    try:
        completed = subprocess.run(
            [command, subcommand, str(source_path), "--language", "ch", "--timeout", str(MINERU_TIMEOUT_SECONDS)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=MINERU_PROCESS_TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="MinerU 转换报告超时，请稍后重试") from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="无法启动 mineru-open-api CLI") from exc
    if completed.returncode != 0:
        if mode == "flash" and completed.returncode == 4:
            detail = "报告超过 MinerU flash-extract 的限制；请配置 Token 并设置 HEALTH_MINERU_MODE=extract"
        elif mode == "extract":
            detail = "MinerU 精确转换失败；请确认已运行 mineru-open-api auth 并检查 Token"
        else:
            detail = "MinerU 未能转换该报告，请确认文件可读后重试"
        raise HTTPException(status_code=422, detail=detail)

    markdown = completed.stdout.strip()
    if not markdown:
        raise HTTPException(status_code=422, detail="MinerU 没有生成可用的 Markdown 文件")
    return markdown


def stage_report(filename: str, content: bytes, content_type: str | None = None) -> dict:
    """Privately stage a report, convert it with MinerU, and return Markdown for AI extraction."""
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
    try:
        source_path = folder / filename
        source_path.write_bytes(content)
        page_count = _pdf_page_count(content) if suffix == ".pdf" else 1
        markdown = _convert_with_mineru(source_path)
        (folder / "mineru.md").write_text(markdown, encoding="utf-8")
        metadata = {"filename": filename, "suffix": suffix, "content_type": content_type or "", "mineru_markdown": "mineru.md"}
        (folder / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        return {
            "id": source_id,
            "filename": filename,
            "page_count": page_count,
            "text": markdown,
            "images": [],
        }
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


@router.post("/imports/stage")
async def stage_upload(file: UploadFile = File(...)) -> dict:
    content = await file.read(MAX_FILE_BYTES + 1)
    return await asyncio.to_thread(stage_report, file.filename or "report", content, file.content_type)


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
    _staged_mineru_markdown(source_id, metadata)
    return source_path, metadata


def _staged_mineru_markdown(source_id: str, metadata: dict) -> Path:
    filename = metadata.get("mineru_markdown")
    if not isinstance(filename, str) or not filename.strip():
        raise HTTPException(status_code=409, detail="暂存报告缺少 MinerU Markdown，请重新上传")
    path = _staging_dir(source_id) / _safe_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=409, detail="暂存报告缺少 MinerU Markdown，请重新上传")
    return path


def _report_markdown(payload: ReportImportCommit, source_rel: str, mineru_rel: str) -> str:
    visit = payload.visit
    lines = [
        f"# {visit.chief_complaint or '体检报告'}",
        "",
        f"- 日期：{visit.date}",
        f"- 机构：{visit.hospital or '未识别'}",
        f"- 原始报告：`{source_rel}`",
        f"- MinerU 转换：`{mineru_rel}`",
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
    mineru_source_path = _staged_mineru_markdown(payload.source_id, metadata)
    date_compact = payload.visit.date.replace("-", "")
    org = _safe_part(payload.visit.hospital, "未知机构")
    item = _safe_part(payload.visit.chief_complaint, "体检报告")
    name = _safe_part(member_name, payload.member_key)
    suffix = metadata["suffix"]
    type_dir = "pdf" if suffix == ".pdf" else "images"
    report_dir = _data_dir() / "reports" / payload.member_key
    raw_dir = report_dir / type_dir
    markdown_dir = report_dir / "md"
    mineru_dir = report_dir / "mineru"
    raw_dir.mkdir(parents=True, exist_ok=True)
    markdown_dir.mkdir(parents=True, exist_ok=True)
    mineru_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{date_compact}_{org}_{item}_{name}"
    raw_path = raw_dir / f"{stem}{suffix}"
    if raw_path.exists():
        raw_path = raw_dir / f"{stem}_{payload.source_id[:6]}{suffix}"
    markdown_path = markdown_dir / f"{raw_path.stem}.md"
    mineru_path = mineru_dir / f"{raw_path.stem}.md"

    # Preserve the original, MinerU conversion, and audited structured summary before writing records.
    shutil.copy2(source_path, raw_path)
    shutil.copy2(mineru_source_path, mineru_path)
    source_rel = raw_path.relative_to(_data_dir().parent).as_posix()
    mineru_rel = mineru_path.relative_to(_data_dir().parent).as_posix()
    markdown_rel = markdown_path.relative_to(_data_dir().parent).as_posix()
    markdown_path.write_text(_report_markdown(payload, source_rel, mineru_rel), encoding="utf-8")
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
                payload.visit.note_full or _report_markdown(payload, source_rel, mineru_rel), markdown_rel,
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
        "mineru_markdown_file": mineru_rel,
        "markdown_file": markdown_rel,
    }
