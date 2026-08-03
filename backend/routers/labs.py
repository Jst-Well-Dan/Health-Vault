from typing import Optional

from fastapi import APIRouter, HTTPException

from database import get_conn
from models import LabRecordCreate, LabUpdate
from routers.common import require_row, row_to_dict, rows_to_dicts


router = APIRouter(tags=["labs"])


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@router.get("/labs")
def list_labs(member: str, panel: Optional[str] = None, visit_id: Optional[int] = None) -> list[dict]:
    where = ["member_key = ?"]
    values: list = [member]
    if panel:
        where.append("panel = ?")
        values.append(panel)
    if visit_id is not None:
        where.append("visit_id = ?")
        values.append(visit_id)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM lab_results WHERE {' AND '.join(where)} ORDER BY date DESC, id DESC",
            values,
        ).fetchall()
        return rows_to_dicts(rows)


@router.get("/labs/available")
def available_labs(member: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT test_name, panel, unit, COUNT(*) AS count
            FROM lab_results
            WHERE member_key = ?
            GROUP BY test_name, panel, unit
            HAVING COUNT(*) >= 2
            ORDER BY test_name
            """,
            (member,),
        ).fetchall()
        return rows_to_dicts(rows)


@router.get("/labs/trend")
def lab_trend(member: str, test_name: str) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT date, value, unit, ref_low, ref_high, status, visit_id
            FROM lab_results
            WHERE member_key = ? AND test_name = ?
            ORDER BY date ASC, id ASC
            """,
            (member, test_name),
        ).fetchall()
    unit = rows[-1]["unit"] if rows else None
    ref_low = rows[-1]["ref_low"] if rows else None
    ref_high = rows[-1]["ref_high"] if rows else None
    points = [
        {
            "date": row["date"],
            "value": _to_float(row["value"]),
            "status": row["status"],
            "visit_id": row["visit_id"],
        }
        for row in rows
        if _to_float(row["value"]) is not None
    ]
    return {"test_name": test_name, "unit": unit, "ref_low": ref_low, "ref_high": ref_high, "points": points}


@router.post("/labs")
def create_lab(payload: LabRecordCreate) -> dict:
    with get_conn() as conn:
        require_row(conn.execute("SELECT key FROM members WHERE key = ?", (payload.member_key,)).fetchone(), "成员不存在")
        if payload.visit_id is not None:
            visit = require_row(
                conn.execute("SELECT member_key FROM visits WHERE id = ?", (payload.visit_id,)).fetchone(),
                "关联就诊记录不存在",
            )
            if visit["member_key"] != payload.member_key:
                raise HTTPException(status_code=422, detail="关联就诊记录不属于当前成员")
        cur = conn.execute(
            """
            INSERT INTO lab_results
              (member_key, visit_id, date, panel, test_name, value, unit, ref_low, ref_high, status, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.member_key, payload.visit_id, payload.date, payload.panel,
                payload.test_name, payload.value, payload.unit, payload.ref_low,
                payload.ref_high, payload.status, payload.source_file,
            ),
        )
        return row_to_dict(conn.execute("SELECT * FROM lab_results WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.patch("/labs/{lab_id}")
def update_lab(lab_id: int, payload: LabUpdate) -> dict:
    data = payload.model_dump(exclude_unset=True)
    with get_conn() as conn:
        current = require_row(
            conn.execute("SELECT id, member_key FROM lab_results WHERE id = ?", (lab_id,)).fetchone(),
            "化验记录不存在",
        )
        if data.get("visit_id") is not None:
            visit = require_row(
                conn.execute("SELECT member_key FROM visits WHERE id = ?", (data["visit_id"],)).fetchone(),
                "关联就诊记录不存在",
            )
            if visit["member_key"] != current["member_key"]:
                raise HTTPException(status_code=422, detail="关联就诊记录不属于当前成员")
        if data:
            conn.execute(
                f"UPDATE lab_results SET {', '.join(f'{field} = ?' for field in data)} WHERE id = ?",
                [*data.values(), lab_id],
            )
        return row_to_dict(conn.execute("SELECT * FROM lab_results WHERE id = ?", (lab_id,)).fetchone())


@router.delete("/labs/{lab_id}")
def delete_lab(lab_id: int) -> dict:
    with get_conn() as conn:
        require_row(conn.execute("SELECT id FROM lab_results WHERE id = ?", (lab_id,)).fetchone(), "化验记录不存在")
        conn.execute("DELETE FROM lab_results WHERE id = ?", (lab_id,))
    return {"ok": True, "id": lab_id}
