import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from database import DB_PATH  # noqa: E402


DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})_")


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._table: list[list[str]] = []
        self._row: list[str] = []
        self._cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
            self._table = []
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._row.append(_clean_text("".join(self._cell)))
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            self._table.append(self._row)
            self._in_row = False
        elif tag == "table" and self._in_table:
            self.tables.append(self._table)
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_DIR).as_posix()
    except ValueError:
        return path.as_posix()


def _extract_tables(path: Path) -> list[list[list[str]]]:
    parser = _TableParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.tables


def _looks_like_result_table(table: list[list[str]]) -> bool:
    if not table:
        return False
    text = "\n".join("|".join(row) for row in table[:3])
    if re.search(r"\d{4}\s*年", text):
        return False
    return (
        ("检查项目" in text and ("测量结果" in text or "检查所见" in text))
        or ("物种" in text and "检测结果" in text)
        or ("乳杆菌" in text and "检测结果" in text)
        or ("条件致病菌" in text and "检测结果" in text)
        or any("乳酸菌比例" in cell for row in table[:2] for cell in row)
    )


def _result_row_count(table: list[list[str]]) -> int:
    if not table:
        return 0
    header_index = None
    for index, row in enumerate(table):
        row_text = "|".join(row)
        if (
            ("检查项目" in row_text and ("测量结果" in row_text or "检查所见" in row_text))
            or ("物种" in row_text and "检测结果" in row_text)
            or ("乳杆菌" in row_text and "检测结果" in row_text)
            or ("条件致病菌" in row_text and "检测结果" in row_text)
        ):
            header_index = index
            break
    if header_index is None:
        return sum(1 for row in table if any(":" in cell or "：" in cell for cell in row))
    if any(re.search(r"\d{4}\s*年", cell) for row in table[header_index + 1 : header_index + 3] for cell in row):
        return 0
    return sum(1 for row in table[header_index + 1 :] if row and row[0] not in {"小结"})


def _payload_lab_count(path: Path, payload_dir: Path | None) -> int | None:
    candidates = []
    if payload_dir:
        candidates.append(payload_dir / f"{path.stem}.json")
    candidates.append(PROJECT_DIR / "data" / "imports" / f"{path.stem}.json")
    for candidate in candidates:
        if candidate.exists():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            return len(payload.get("labs", []))
    return None


def _db_lab_count(path: Path, member_key: str) -> int | str | None:
    match = DATE_RE.match(path.name)
    if not match or not DB_PATH.exists():
        return None
    visit_date = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    project_path = _project_path(path)
    with sqlite3.connect(DB_PATH) as conn:
        exact = conn.execute(
            """
            SELECT COUNT(l.id)
            FROM visits v
            LEFT JOIN lab_results l ON l.visit_id = v.id
            WHERE v.member_key = ?
              AND v.date = ?
              AND (v.source_file = ? OR v.source_file = ?)
            """,
            (member_key, visit_date, project_path, path.name),
        ).fetchone()
        if exact and exact[0]:
            return int(exact[0])

        rows = conn.execute(
            """
            SELECT v.id, COUNT(l.id)
            FROM visits v
            LEFT JOIN lab_results l ON l.visit_id = v.id
            WHERE v.member_key = ?
              AND v.date = ?
            GROUP BY v.id
            ORDER BY v.id
            """,
            (member_key, visit_date),
        ).fetchall()
    if len(rows) == 1:
        return int(rows[0][1])
    if len(rows) > 1:
        return "ambiguous:" + ",".join(f"visit={row[0]} labs={row[1]}" for row in rows)
    return None


def audit_file(path: Path, member_key: str, payload_dir: Path | None) -> dict:
    tables = _extract_tables(path)
    result_tables = [table for table in tables if _looks_like_result_table(table)]
    return {
        "file": _project_path(path),
        "tables": len(tables),
        "result_tables": len(result_tables),
        "table_rows_excluding_first_row": sum(max(len(table) - 1, 0) for table in tables),
        "estimated_result_rows": sum(_result_row_count(table) for table in result_tables),
        "payload_labs": _payload_lab_count(path, payload_dir),
        "db_labs": _db_lab_count(path, member_key),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit report tables against generated payloads and database lab rows.")
    parser.add_argument("files", nargs="+", help="Markdown report files to audit.")
    parser.add_argument("--member", default="chunzi", help="Member key for database comparison.")
    parser.add_argument("--payload-dir", help="Directory containing generated JSON payloads.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a compact table.")
    args = parser.parse_args()

    payload_dir = Path(args.payload_dir).resolve() if args.payload_dir else None
    rows = [audit_file(Path(file), args.member, payload_dir) for file in args.files]

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    print("file\ttables\tresult_tables\test_result_rows\tpayload_labs\tdb_labs")
    for row in rows:
        print(
            "\t".join(
                str(row[key])
                for key in ["file", "tables", "result_tables", "estimated_result_rows", "payload_labs", "db_labs"]
            )
        )


if __name__ == "__main__":
    main()
