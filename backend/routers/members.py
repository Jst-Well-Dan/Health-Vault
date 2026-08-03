import re
import secrets
from typing import Any
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException

from database import get_conn
from models import MemberCreate, MemberUpdate
from routers.common import json_dumps, json_loads, require_row


router = APIRouter(tags=["members"])
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "data" / "public"
AVATAR_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
ALLOWED_SPECIES = {"human", "cat", "dog", "other"}


def _public_url(path: Path) -> str:
    rel = path.relative_to(PUBLIC_DIR).as_posix()
    return "/public/" + quote(rel)


def _find_avatar_url(member_key: str) -> str | None:
    if not PUBLIC_DIR.exists():
        return None

    key = str(member_key or "").strip().lower()
    if not key:
        return None

    for path in sorted(PUBLIC_DIR.rglob("*")):
        if path.is_file() and path.suffix.lower() in AVATAR_EXTS and path.stem.lower() == key:
            return _public_url(path)
    return None


def _member_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["allergies"] = json_loads(item.get("allergies"))
    item["chronic"] = json_loads(item.get("chronic"))
    item["avatar_url"] = _find_avatar_url(item.get("key", ""))
    return item


def _validate_key(key: str) -> str:
    key = str(key or "").strip()
    if not SAFE_KEY_RE.fullmatch(key):
        raise HTTPException(status_code=422, detail="成员 key 只能包含 1-64 位英文字母、数字、下划线或连字符，且必须以字母或数字开头")
    return key


def _generate_key(conn: Any, species: str) -> str:
    prefix = "member" if species == "human" else "pet"
    for _ in range(10):
        key = f"{prefix}-{secrets.token_hex(4)}"
        exists = conn.execute("SELECT 1 FROM members WHERE key = ?", (key,)).fetchone()
        if not exists:
            return key
    raise HTTPException(status_code=500, detail="无法生成唯一成员 key")


def _validate_member_payload(data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="成员姓名不能为空")
    species = str(data.get("species") or "").strip()
    if not species:
        raise HTTPException(status_code=422, detail="species 不能为空")
    if species not in ALLOWED_SPECIES:
        raise HTTPException(status_code=422, detail=f"species 仅支持：{', '.join(sorted(ALLOWED_SPECIES))}")
    data["name"] = name
    data["species"] = species
    return data


@router.get("/members")
def list_members(include_archived: bool = False) -> list[dict[str, Any]]:
    where = "" if include_archived else "WHERE archived_at IS NULL"
    with get_conn() as conn:
        rows = conn.execute(f"SELECT * FROM members {where} ORDER BY sort_order, created_at, key").fetchall()
        return [_member_dict(row) for row in rows]


@router.post("/members", status_code=201)
def create_member(payload: MemberCreate) -> dict[str, Any]:
    data = _validate_member_payload(payload.model_dump(exclude_unset=True))
    allowed = {
        "key", "name", "full_name", "initial", "birth_date", "sex", "blood_type", "role",
        "species", "sort_order", "breed", "home_date", "chip_id", "doctor", "allergies", "chronic", "notes",
    }
    with get_conn() as conn:
        key = data.get("key")
        if key:
            key = _validate_key(key)
            if conn.execute("SELECT 1 FROM members WHERE key = ?", (key,)).fetchone():
                raise HTTPException(status_code=409, detail="成员 key 已存在")
        else:
            key = _generate_key(conn, data["species"])
        data["key"] = key
        if data.get("sort_order") is None:
            max_sort_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS value FROM members").fetchone()["value"]
            data["sort_order"] = max_sort_order + 10
        fields = []
        values = []
        for field in allowed:
            if field not in data:
                continue
            value = data[field]
            if field in {"allergies", "chronic"}:
                value = json_dumps(value)
            fields.append(field)
            values.append(value)
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(f"INSERT INTO members ({', '.join(fields)}) VALUES ({placeholders})", values)
    return get_member(key)


@router.get("/members/{key}")
def get_member(key: str) -> dict[str, Any]:
    with get_conn() as conn:
        row = require_row(conn.execute("SELECT * FROM members WHERE key = ?", (key,)).fetchone(), "成员不存在")
        return _member_dict(row)


@router.patch("/members/{key}")
def update_member(key: str, payload: MemberUpdate) -> dict[str, Any]:
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return get_member(key)

    allowed = {
        "name", "full_name", "initial", "birth_date", "sex", "blood_type", "role",
        "species", "sort_order", "breed", "home_date", "chip_id", "doctor", "allergies", "chronic", "notes", "archived_at",
    }
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="成员姓名不能为空")
        data["name"] = name
    if "species" in data:
        species = str(data.get("species") or "").strip()
        if not species:
            raise HTTPException(status_code=422, detail="species 不能为空")
        if species not in ALLOWED_SPECIES:
            raise HTTPException(status_code=422, detail=f"species 仅支持：{', '.join(sorted(ALLOWED_SPECIES))}")
        data["species"] = species

    updates = []
    values = []
    for field, value in data.items():
        if field not in allowed:
            continue
        if field in {"allergies", "chronic"}:
            value = json_dumps(value)
        updates.append(f"{field} = ?")
        values.append(value)
    updates.append("updated_at = datetime('now','localtime')")
    values.append(key)

    with get_conn() as conn:
        require_row(conn.execute("SELECT key FROM members WHERE key = ?", (key,)).fetchone(), "成员不存在")
        conn.execute(f"UPDATE members SET {', '.join(updates)} WHERE key = ?", values)
    return get_member(key)
