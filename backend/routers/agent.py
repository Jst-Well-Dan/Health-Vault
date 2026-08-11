import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_conn
from routers.common import row_to_dict, rows_to_dicts


router = APIRouter(tags=["agent"])

TABLE_KEYS = {
    "members": "key",
    "visits": "id",
    "lab_results": "id",
    "meds": "id",
    "weight_log": "id",
    "reminders": "id",
    "attachments": "id",
}


class ChangeCreate(BaseModel):
    tool: str
    table_name: str
    row_id: str | int
    action: Literal["create", "update", "delete"]
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class MessageCreate(BaseModel):
    session_id: str = "default"
    role: Literal["user", "assistant"]
    content: str


def _snapshot(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value else None


@router.post("/agent/changes")
def log_change(payload: ChangeCreate) -> dict:
    if payload.table_name not in TABLE_KEYS:
        raise HTTPException(status_code=400, detail="不允许记录该数据表")
    if payload.action == "create" and not payload.after:
        raise HTTPException(status_code=400, detail="新增操作缺少 after 快照")
    if payload.action in {"update", "delete"} and not payload.before:
        raise HTTPException(status_code=400, detail="修改操作缺少 before 快照")
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_change_log (tool, table_name, row_id, action, before_json, after_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.tool, payload.table_name, str(payload.row_id), payload.action,
                json.dumps(payload.before, ensure_ascii=False) if payload.before else None,
                json.dumps(payload.after, ensure_ascii=False) if payload.after else None,
            ),
        )
        return {"id": cur.lastrowid, "ok": True}


@router.get("/agent/changes")
def list_changes(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute(
            "SELECT * FROM agent_change_log ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall())
    for row in rows:
        row["before"] = _snapshot(row.pop("before_json"))
        row["after"] = _snapshot(row.pop("after_json"))
    return rows


@router.get("/agent/records/{table_name}/{row_id}")
def get_record(table_name: str, row_id: str) -> dict:
    key = TABLE_KEYS.get(table_name)
    if not key:
        raise HTTPException(status_code=400, detail="不允许读取该数据表")
    with get_conn() as conn:
        row = conn.execute(f"SELECT * FROM {table_name} WHERE {key} = ?", (row_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    return row_to_dict(row)


@router.post("/agent/undo")
def undo_last_change() -> dict:
    with get_conn() as conn:
        change = conn.execute(
            "SELECT * FROM agent_change_log WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not change:
            raise HTTPException(status_code=404, detail="没有可撤销的改动")

        table = change["table_name"]
        key = TABLE_KEYS.get(table)
        if not key:
            raise HTTPException(status_code=400, detail="该改动不可撤销")
        before = _snapshot(change["before_json"])
        after = _snapshot(change["after_json"])

        if change["action"] == "create":
            conn.execute(f"DELETE FROM {table} WHERE {key} = ?", (change["row_id"],))
        elif change["action"] == "update":
            _restore_row(conn, table, key, before)
        else:
            _insert_row(conn, table, before)

        conn.execute("UPDATE agent_change_log SET undone_at = datetime('now','localtime') WHERE id = ?", (change["id"],))
        return {"ok": True, "change_id": change["id"], "tool": change["tool"], "restored": before or after}


def _restore_row(conn, table: str, key: str, row: dict[str, Any] | None) -> None:
    if not row:
        raise HTTPException(status_code=400, detail="撤销快照缺失")
    values = {field: value for field, value in row.items() if field != key}
    conn.execute(
        f"UPDATE {table} SET {', '.join(f'{field} = ?' for field in values)} WHERE {key} = ?",
        [*values.values(), row[key]],
    )


def _insert_row(conn, table: str, row: dict[str, Any] | None) -> None:
    if not row:
        raise HTTPException(status_code=400, detail="撤销快照缺失")
    conn.execute(
        f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
        list(row.values()),
    )


@router.get("/agent/messages")
def list_messages(session_id: str = "default", limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        return rows_to_dicts(conn.execute(
            "SELECT * FROM agent_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, max(1, min(limit, 500))),
        ).fetchall())[::-1]


@router.post("/agent/messages")
def create_message(payload: MessageCreate) -> dict:
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息不能为空")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agent_messages (session_id, role, content) VALUES (?, ?, ?)",
            (payload.session_id, payload.role, content),
        )
        return row_to_dict(conn.execute("SELECT * FROM agent_messages WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.delete("/agent/messages")
def clear_messages(session_id: str = "default") -> dict:
    with get_conn() as conn:
        conn.execute("DELETE FROM agent_messages WHERE session_id = ?", (session_id,))
    return {"ok": True}
