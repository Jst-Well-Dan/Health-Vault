"""跨表检索与多指标趋势：给健康助手的「找得到」能力。

* `/api/records/search`：一个关键词跨就诊、化验、用药、提醒、附件检索，返回带来源的命中片段。
* `/api/labs/history`：一次取多个指标的完整序列，避免逐个指标来回调用。

两个接口都主动截断长文本（notes/note_full 等），避免助手上下文被一份报告塞满。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_conn
from routers.common import rows_to_dicts


router = APIRouter(tags=["search"])

SNIPPET_CHARS = 240
DEFAULT_LIMIT = 30
MAX_LIMIT = 100
MAX_TESTS = 20
MAX_POINTS_PER_TEST = 120

# table -> (对外名称, 参与检索的文本列, 结果排序)
SEARCH_TABLES: dict[str, tuple[str, list[str], str]] = {
    "visits": ("就诊记录", ["date", "type", "hospital", "department", "doctor", "chief_complaint", "diagnosis", "notes", "note_full"], "date DESC, id DESC"),
    "lab_results": ("化验结果", ["date", "panel", "test_name", "value", "unit"], "date DESC, id DESC"),
    "meds": ("用药", ["name", "dose", "freq", "route", "category", "notes"], "start_date DESC, id DESC"),
    "pet_care_logs": ("宠物记事", ["date", "kind", "notes"], "date DESC, id DESC"),
    "attachments": ("附件", ["date", "title", "org", "tag", "filename", "file_path", "notes"], "date DESC, id DESC"),
    "members": ("成员资料", ["name", "full_name", "allergies", "chronic", "notes"], "sort_order ASC, key ASC"),
}


def _snippet(row: dict, columns: list[str], keyword: str) -> dict:
    """返回命中的字段与截断后的片段，便于助手引用来源。"""
    fields = {key: row[key] for key in columns if row.get(key) not in (None, "")}
    for key, value in fields.items():
        text = str(value)
        position = text.lower().find(keyword.lower())
        if position >= 0:
            start = max(0, position - 40)
            return {"matched_field": key, "snippet": text[start : start + SNIPPET_CHARS]}
    first = next((str(value) for value in fields.values()), "")
    return {"matched_field": next(iter(fields), None), "snippet": first[:SNIPPET_CHARS]}


@router.get("/records/search")
def search_records(
    q: str = Query(min_length=1, max_length=120),
    member: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    tables: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """跨表关键词检索。`tables` 用逗号指定子集（默认全部）。"""
    keyword = q.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="检索关键词不能为空")
    limit = max(1, min(limit, MAX_LIMIT))
    requested = [name.strip() for name in tables.split(",")] if tables else list(SEARCH_TABLES)
    unknown = [name for name in requested if name not in SEARCH_TABLES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"不支持检索的表：{', '.join(unknown)}")

    like = f"%{keyword}%"
    results: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    with get_conn() as conn:
        for table in requested:
            label, text_columns, order = SEARCH_TABLES[table]
            where = ["(" + " OR ".join(f"{column} LIKE ?" for column in text_columns) + ")"]
            values: list = [like] * len(text_columns)
            if member and table != "members":
                where.append("member_key = ?")
                values.append(member)
            elif member and table == "members":
                where.append("key = ?")
                values.append(member)
            date_column = "date" if table != "meds" else "start_date"
            if date_from:
                where.append(f"{date_column} >= ?")
                values.append(date_from)
            if date_to:
                where.append(f"{date_column} <= ?")
                values.append(date_to)
            clause = " AND ".join(where)
            total = conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE {clause}", values).fetchone()["c"]
            rows = rows_to_dicts(conn.execute(f"SELECT * FROM {table} WHERE {clause} ORDER BY {order} LIMIT ?", [*values, limit]).fetchall())
            counts[table] = total
            results[table] = [{"table": table, "table_label": label, **row, **_snippet(row, text_columns, keyword)} for row in rows]

    return {
        "query": keyword,
        "member": member,
        "date_from": date_from,
        "date_to": date_to,
        "counts": counts,
        "total_hits": sum(counts.values()),
        "results": results,
        "truncated": any(counts[table] > len(results[table]) for table in requested),
    }


@router.get("/labs/history")
def lab_history(
    member: str,
    tests: str = Query(min_length=1, description="指标名，逗号分隔"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit_per_test: int = MAX_POINTS_PER_TEST,
) -> dict:
    """一次返回多个化验指标的时间序列（按日期升序），缺失的指标单独列出。"""
    wanted: list[str] = []
    for raw in tests.split(","):
        name = raw.strip()
        if name and name not in wanted:
            wanted.append(name)
    if not wanted:
        raise HTTPException(status_code=400, detail="请至少提供一个指标名")
    if len(wanted) > MAX_TESTS:
        raise HTTPException(status_code=400, detail=f"一次最多查询 {MAX_TESTS} 个指标")
    limit_per_test = max(1, min(limit_per_test, MAX_POINTS_PER_TEST))

    where = ["member_key = ?", "LOWER(test_name) IN (" + ",".join("?" for _ in wanted) + ")"]
    values: list = [member, *[name.lower() for name in wanted]]
    if date_from:
        where.append("date >= ?")
        values.append(date_from)
    if date_to:
        where.append("date <= ?")
        values.append(date_to)

    series: dict[str, list[dict]] = {name: [] for name in wanted}
    canonical: dict[str, str] = {}
    with get_conn() as conn:
        rows = rows_to_dicts(
            conn.execute(
                f"""
                SELECT date, test_name, value, unit, ref_low, ref_high, status, panel, source_file
                FROM lab_results
                WHERE {' AND '.join(where)}
                ORDER BY date ASC, id ASC
                """,
                values,
            ).fetchall()
        )
    for row in rows:
        key = str(row["test_name"]).strip()
        name = next((item for item in wanted if item.lower() == key.lower()), key)
        series.setdefault(name, []).append(row)
        canonical.setdefault(name.lower(), key)

    for name in wanted:
        points = series.get(name, [])
        if len(points) > limit_per_test:
            series[name] = points[-limit_per_test:]

    return {
        "member": member,
        "tests": {name: series.get(name, []) for name in wanted},
        "counts": {name: len(series.get(name, [])) for name in wanted},
        "missing": [name for name in wanted if not series.get(name)],
        "canonical_names": {name: canonical.get(name.lower(), name) for name in wanted},
        "date_from": date_from,
        "date_to": date_to,
    }
