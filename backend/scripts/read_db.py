"""只读查询 health.db。SQL 全部写死在代码里，不接受外部 SQL。

连接以只读模式打开，任何写入都会直接报错。输出默认精简，
给 agent 拼回答用，不是给人翻全表用。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from database import DB_PATH  # noqa: E402


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _print(rows: list[dict]) -> None:
    print(json.dumps(rows, ensure_ascii=False, indent=1))


def cmd_meds(args: argparse.Namespace) -> None:
    """某成员吃过/在吃哪些药。"""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT name, dose, freq, route, start_date, end_date, ongoing, notes
            FROM meds WHERE member_key = ? ORDER BY start_date DESC, id DESC
            """,
            (args.member,),
        ).fetchall()
    _print([dict(r) for r in rows])


def cmd_labs(args: argparse.Namespace) -> None:
    """某成员某指标的历史值。--latest 只取最近一条。"""
    sql = """
        SELECT date, panel, test_name, value, unit, ref_low, ref_high, status
        FROM lab_results WHERE member_key = ?
        """
    values: list = [args.member]
    if args.test:
        sql += " AND test_name LIKE ?"
        values.append(f"%{args.test}%")
    sql += " ORDER BY date DESC, id DESC"
    if args.latest:
        sql += " LIMIT 1"
    elif args.limit:
        sql += f" LIMIT {int(args.limit)}"
    with _connect() as conn:
        rows = conn.execute(sql, values).fetchall()
    _print([dict(r) for r in rows])


def cmd_visits(args: argparse.Namespace) -> None:
    """某成员最近的就诊摘要。"""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, date, type, hospital, department, chief_complaint,
                   severity, diagnosis, notes
            FROM visits WHERE member_key = ? ORDER BY date DESC, id DESC LIMIT ?
            """,
            (args.member, args.limit),
        ).fetchall()
    _print([dict(r) for r in rows])


def cmd_attachments(args: argparse.Namespace) -> None:
    """某次就诊的附件清单（含 file_path，agent 顺着读原文）。"""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, org, tag, filename, file_path, notes
            FROM attachments WHERE visit_id = ? ORDER BY id ASC
            """,
            (args.visit,),
        ).fetchall()
    _print([dict(r) for r in rows])


def cmd_search(args: argparse.Namespace) -> None:
    """关键词跨表检索：就诊、用药、记事、化验。"""
    like = f"%{args.keyword}%"
    out: list[dict] = []
    with _connect() as conn:
        for row in conn.execute(
            """
            SELECT 'visit' AS kind, id, member_key, date, chief_complaint AS snippet
            FROM visits WHERE chief_complaint LIKE ? OR diagnosis LIKE ? OR notes LIKE ?
            """,
            (like, like, like),
        ).fetchall():
            out.append(dict(row))
        for row in conn.execute(
            "SELECT 'med' AS kind, id, member_key, start_date AS date, name AS snippet"
            " FROM meds WHERE name LIKE ? OR notes LIKE ?",
            (like, like),
        ).fetchall():
            out.append(dict(row))
        for row in conn.execute(
            "SELECT 'lab' AS kind, id, member_key, date, test_name || ' ' || value AS snippet"
            " FROM lab_results WHERE test_name LIKE ? OR panel LIKE ?",
            (like, like),
        ).fetchall():
            out.append(dict(row))
        for row in conn.execute(
            "SELECT 'care' AS kind, id, member_key, date, kind || ' ' || COALESCE(notes,'') AS snippet"
            " FROM pet_care_logs WHERE kind LIKE ? OR notes LIKE ?",
            (like, like),
        ).fetchall():
            out.append(dict(row))
    _print(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_meds = sub.add_parser("meds", help="某成员的用药")
    p_meds.add_argument("--member", required=True)
    p_meds.set_defaults(func=cmd_meds)

    p_labs = sub.add_parser("labs", help="某成员的指标历史")
    p_labs.add_argument("--member", required=True)
    p_labs.add_argument("--test", default=None, help="指标名模糊匹配")
    p_labs.add_argument("--latest", action="store_true", help="只取最近一条")
    p_labs.add_argument("--limit", type=int, default=10)
    p_labs.set_defaults(func=cmd_labs)

    p_visits = sub.add_parser("visits", help="某成员最近就诊")
    p_visits.add_argument("--member", required=True)
    p_visits.add_argument("--limit", type=int, default=5)
    p_visits.set_defaults(func=cmd_visits)

    p_search = sub.add_parser("search", help="关键词跨表检索")
    p_search.add_argument("keyword")
    p_search.set_defaults(func=cmd_search)

    p_att = sub.add_parser("attachments", help="某次就诊的附件清单")
    p_att.add_argument("--visit", type=int, required=True)
    p_att.set_defaults(func=cmd_attachments)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
