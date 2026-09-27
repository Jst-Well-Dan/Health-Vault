import os
from typing import Any
from pathlib import Path
from urllib.parse import quote

import database
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from database import get_conn
from models import AvatarPresetApply, MemberCreate, MemberUpdate
from routers.common import json_loads, require_row
from services.writes import (
    ConflictError,
    PayloadError,
    ValidationError,
    create_member_record,
    update_member_record,
    validate_member_key,
)


router = APIRouter(tags=["members"])
# 顺序即优先级：同名时按这里的前后决定用哪张（不能是 set，否则解析结果随机）。
AVATAR_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MAX_AVATAR_BYTES = 5 * 1024 * 1024


def _avatar_storage_dir() -> Path:
    """成员头像目录：仓库根目录的 `public/`。

    属于私有运行数据（家人照片），已在 `.gitignore` 里整体排除。
    可用 `HEALTH_PUBLIC_DIR` 覆盖，供测试指向临时目录。
    """
    configured = os.getenv("HEALTH_PUBLIC_DIR")
    if configured:
        return Path(configured).resolve()
    return (Path(__file__).resolve().parents[2] / "public").resolve()


def _find_avatar_in(directory: Path, key: str) -> Path | None:
    for suffix in AVATAR_EXTS:
        path = directory / f"{key}{suffix}"
        if path.is_file():
            return path
    return None


def _find_avatar_file(member_key: str) -> Path | None:
    key = str(member_key or "").strip().lower()
    if not key:
        return None
    return _find_avatar_in(_avatar_storage_dir(), key)


def _find_avatar_url(member_key: str) -> str | None:
    key = str(member_key or "").strip().lower()
    if not key:
        return None
    avatar = _find_avatar_file(key)
    if not avatar:
        return None
    return f"/api/members/{quote(key)}/avatar?v={avatar.stat().st_mtime_ns}"


def _preset_dir() -> Path:
    """预设头像库目录：默认 frontend/assets/avatars，可用 HEALTH_AVATARS_DIR 覆盖。

    与 main.py 的前端目录解析保持一致（优先 HEALTH_FRONTEND_DIR，否则按代码位置推导），
    不跟随 HEALTH_VAULT_HOME——预设属于应用自带资源，不属于私有数据。
    """
    configured = os.getenv("HEALTH_AVATARS_DIR")
    if configured:
        return Path(configured).resolve()
    frontend_dir = os.getenv("HEALTH_FRONTEND_DIR")
    if not frontend_dir:
        repo_root = Path(__file__).resolve().parents[2]
        frontend_dir = str(repo_root / "frontend")
    return (Path(frontend_dir).resolve() / "assets" / "avatars").resolve()


def _resolve_preset(name: str) -> Path | None:
    """解析预设头像文件；拒绝路径穿越、非白名单扩展名或超限文件。"""
    directory = _preset_dir()
    try:
        candidate = (directory / str(name or "")).resolve()
    except (OSError, ValueError):
        return None
    if directory not in [candidate, *candidate.parents]:
        return None
    if not candidate.is_file():
        return None
    if candidate.suffix.lower() not in AVATAR_EXTS:
        return None
    if candidate.stat().st_size > MAX_AVATAR_BYTES:
        return None
    return candidate


def _verify_image_signature(suffix: str, content: bytes) -> bool:
    signatures = {
        ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": content.startswith(b"\xff\xd8\xff"),
        ".jpeg": content.startswith(b"\xff\xd8\xff"),
        ".gif": content.startswith((b"GIF87a", b"GIF89a")),
        ".webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
    }
    return signatures.get(suffix, False)


@router.get("/avatars/presets")
def list_avatar_presets() -> list[dict[str, str]]:
    """列出预设头像库中的可选图片（白名单扩展名、大小上限内）。"""
    directory = _preset_dir()
    if not directory.is_dir():
        return []
    items: list[dict[str, str]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in AVATAR_EXTS:
            continue
        if path.stat().st_size > MAX_AVATAR_BYTES:
            continue
        name = path.name
        items.append({"name": name, "url": f"/api/avatars/presets/{quote(name)}"})
    return items


@router.get("/avatars/presets/{name}")
def get_avatar_preset(name: str) -> FileResponse:
    """返回预设头像图片文件（带缓存头）。"""
    path = _resolve_preset(name)
    if not path:
        raise HTTPException(status_code=404, detail="预设头像不存在")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


def _member_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item.pop("chip_id", None)
    item["allergies"] = json_loads(item.get("allergies"))
    item["chronic"] = json_loads(item.get("chronic"))
    item["avatar_url"] = _find_avatar_url(item.get("key", ""))
    return item


def _validate_key(key: str) -> str:
    try:
        return validate_member_key(key)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/members", status_code=201)
def create_member(payload: MemberCreate) -> dict[str, Any]:
    try:
        key = create_member_record(payload.model_dump(exclude_unset=True))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return get_member(key)


@router.get("/members")
def list_members(include_archived: bool = False) -> list[dict[str, Any]]:
    where = "" if include_archived else "WHERE archived_at IS NULL"
    with get_conn() as conn:
        rows = conn.execute(f"SELECT * FROM members {where} ORDER BY sort_order, created_at, key").fetchall()
        return [_member_dict(row) for row in rows]


@router.patch("/members/{key}")
def update_member(key: str, payload: MemberUpdate) -> dict[str, Any]:
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return get_member(key)
    try:
        update_member_record(key, data)
    except PayloadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return get_member(key)


@router.get("/members/{key}/avatar")
def get_avatar(key: str) -> FileResponse:
    _validate_key(key)
    path = _find_avatar_file(key)
    if not path:
        raise HTTPException(status_code=404, detail="成员头像不存在")
    return FileResponse(path)


@router.post("/members/{key}/avatar")
async def upload_avatar(key: str, file: UploadFile = File(...)) -> dict[str, Any]:
    _validate_key(key)
    with get_conn(log_writes=False) as conn:
        require_row(conn.execute("SELECT key FROM members WHERE key = ?", (key,)).fetchone(), "成员不存在")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in AVATAR_EXTS:
        raise HTTPException(status_code=400, detail="头像仅支持 JPG、PNG、WEBP 或 GIF 图片")
    content = await file.read(MAX_AVATAR_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="头像文件为空")
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="头像不能超过 5MB")

    if not _verify_image_signature(suffix, content):
        raise HTTPException(status_code=400, detail="头像文件内容与扩展名不匹配")

    avatar_dir = _avatar_storage_dir()
    avatar_dir.mkdir(parents=True, exist_ok=True)
    for old_suffix in AVATAR_EXTS:
        old_path = avatar_dir / f"{key}{old_suffix}"
        if old_path.is_file():
            old_path.unlink()
    target = avatar_dir / f"{key}{suffix}"
    temp = avatar_dir / f".{key}{suffix}.tmp"
    try:
        temp.write_bytes(content)
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()
    return get_member(key)


@router.post("/members/{key}/avatar/preset")
def apply_preset_avatar(key: str, payload: AvatarPresetApply) -> dict[str, Any]:
    """将预设头像库中的图片复制为该成员头像（与上传同存储，覆盖旧头像）。"""
    _validate_key(key)
    with get_conn(log_writes=False) as conn:
        require_row(conn.execute("SELECT key FROM members WHERE key = ?", (key,)).fetchone(), "成员不存在")

    name = str(payload.name or "").strip()
    source = _resolve_preset(name)
    if not source:
        raise HTTPException(status_code=404, detail="预设头像不存在")

    content = source.read_bytes()
    if not content:
        raise HTTPException(status_code=400, detail="预设头像文件为空")

    suffix = source.suffix.lower()
    if not _verify_image_signature(suffix, content):
        raise HTTPException(status_code=400, detail="头像文件内容与扩展名不匹配")

    avatar_dir = _avatar_storage_dir()
    avatar_dir.mkdir(parents=True, exist_ok=True)
    for old_suffix in AVATAR_EXTS:
        old_path = avatar_dir / f"{key}{old_suffix}"
        if old_path.is_file():
            old_path.unlink()
    target = avatar_dir / f"{key}{suffix}"
    temp = avatar_dir / f".{key}{suffix}.tmp"
    try:
        temp.write_bytes(content)
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()
    return get_member(key)


@router.get("/members/{key}")
def get_member(key: str) -> dict[str, Any]:
    with get_conn() as conn:
        row = require_row(conn.execute("SELECT * FROM members WHERE key = ?", (key,)).fetchone(), "成员不存在")
        return _member_dict(row)
