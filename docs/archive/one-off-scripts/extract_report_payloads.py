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


DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})_([^_]+)_([^_]+)_(.+)$")
TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._in_row = False
        self._in_cell = False
        self._row: list[str] = []
        self._cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
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
            self.rows.append(self._row)
            self._in_row = False

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


def _parse_table(html: str) -> list[list[str]]:
    parser = _TableParser()
    parser.feed(html)
    return parser.rows


def _date_from_name(path: Path) -> str:
    match = DATE_RE.match(path.stem)
    if not match:
        raise ValueError(f"report filename must start with YYYYMMDD_: {path}")
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _title_parts(path: Path) -> tuple[str, str, str]:
    match = DATE_RE.match(path.stem)
    if not match:
        return "", "", path.stem
    return match.group(4), match.group(5), match.group(6)


def _load_existing_visit(member_key: str, visit_date: str) -> dict | None:
    if not DB_PATH.exists():
        return None
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            """
            SELECT date, type, hospital, department, doctor, chief_complaint,
                   severity, diagnosis, notes, note_full
            FROM visits
            WHERE member_key = ? AND date = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (member_key, visit_date),
        ).fetchone()


def _diagnosis(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            return [value]
    return []


def _default_note_full(item: str) -> str:
    return (
        "### 医生诊断\n"
        "报告未列出明确诊断。\n\n"
        "### 诊疗意见\n"
        f"{item}报告已归档，导入前需根据报告结论、异常指标和复查建议补充高信号摘要。\n\n"
        "### 治疗方案说明\n"
        "报告中未提供具体用药或治疗方案。"
    )


def _nearest_panel(prefix: str, table: list[list[str]]) -> str:
    if table and len(table[0]) == 1 and table[0][0]:
        text = re.sub(r"\s*(检查者|操作者|审核者)[:：]?.*$", "", table[0][0]).strip(" ·")
        if text:
            return text

    prefix = TABLE_RE.sub("\n", prefix)
    lines = [_clean_text(re.sub(r"<[^>]+>", " ", line).strip("# ").strip()) for line in prefix.splitlines()]
    skip = {"", "检查项目", "测量结果", "参考区间", "单位", "提示"}
    for line in reversed(lines[-20:]):
        if (
            line in skip
            or line in {"正常", "异常", "-", "—"}
            or line.startswith("Θ")
            or line.startswith("!")
            or line.endswith(("。", "；", ";"))
            or "检查者" in line
            or "审核者" in line
            or "操作者" in line
            or len(line) > 40
        ):
            continue
        return line.strip(" ·")
    return "报告表格"


def _southgene_panel(path: Path, table_index: int) -> str | None:
    if "南方基因" not in path.name:
        return None
    return {
        2: "菌群检测概览",
        3: "乳杆菌",
        4: "条件致病菌",
        5: "疾病风险总览",
        6: "细菌性阴道病(BV)",
        7: "需氧菌性阴道病(AV)",
        8: "外阴阴道假丝酵母菌病(VVC)",
        9: "滴虫性阴道病(TV)",
        10: "生殖道支原体感染",
        11: "生殖器疱疹",
        12: "沙眼衣原体感染",
        13: "软下疳",
    }.get(table_index)


def _header_index(table: list[list[str]]) -> int | None:
    for index, row in enumerate(table):
        text = "|".join(row)
        if (
            ("检查项目" in text and ("测量结果" in text or "检查所见" in text))
            or ("物种" in text and "检测结果" in text)
            or ("乳杆菌" in text and "检测结果" in text)
            or ("条件致病菌" in text and "检测结果" in text)
        ):
            return index
    return None


def _column_map(header: list[str]) -> dict[str, int]:
    mapping = {}
    for index, name in enumerate(header):
        if "检查项目" in name or "物种" in name or name in {"乳杆菌", "条件致病菌"}:
            mapping["name"] = index
        elif "测量结果" in name or "检查所见" in name or "检测结果" in name:
            mapping["value"] = index
        elif "单位" in name:
            mapping["unit"] = index
        elif "参考" in name or "正常范围" in name or "正常参考值" in name:
            mapping["ref"] = index
        elif "提示" in name or "异常描述" in name or "风险评估" in name:
            mapping["status"] = index
        elif "缩写" in name:
            mapping["abbr"] = index
    return mapping


def _cell(row: list[str], index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    value = row[index].strip()
    return value or None


def _clean_name(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^[★■*·\s]+", "", value)
    value = re.sub(r"^(HR|H R)\s*", "", value)
    value = value.replace("↑", "").replace("↓", "").strip()
    return value or None


def _parse_reference(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    value = value.strip().replace("—", "-").replace("--", "-").replace("～", "-").replace("~", "-")
    value = value.replace(" ", "")
    if value in {"阴性", "未检出"}:
        return value, None
    if value.startswith(("≤", "<")):
        return None, value.lstrip("≤<")
    if value.startswith(("≥", ">")):
        return value.lstrip("≥>"), None
    match = re.match(r"^(-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)$", value)
    if match:
        return match.group(1), match.group(2)
    return None, value if value and not re.fullmatch(r"-?\d+(?:\.\d+)?", value) else None


def _status(value: str | None, marker: str | None, ref_low: str | None, ref_high: str | None) -> str:
    marker_text = marker or ""
    value_text = value or ""
    if "↑" in marker_text or marker_text.upper() == "H" or "增高" in marker_text:
        return "high"
    if "↓" in marker_text or marker_text.upper() == "L" or "降低" in marker_text:
        return "low"
    if "阳性" in value_text and ref_low == "阴性":
        return "abnormal"
    if value_text in {"阴性", "未检出"}:
        return "normal"
    try:
        number = float(re.search(r"-?\d+(?:\.\d+)?", value_text).group(0))  # type: ignore[union-attr]
        if ref_low and re.fullmatch(r"-?\d+(?:\.\d+)?", ref_low) and number < float(ref_low):
            return "low"
        if ref_high and re.fullmatch(r"-?\d+(?:\.\d+)?", ref_high) and number > float(ref_high):
            return "high"
        if (ref_low and re.fullmatch(r"-?\d+(?:\.\d+)?", ref_low)) or (
            ref_high and re.fullmatch(r"-?\d+(?:\.\d+)?", ref_high)
        ):
            return "normal"
    except AttributeError:
        pass
    return "unknown"


def _lab(panel: str, source_file: str, row: list[str], mapping: dict[str, int]) -> dict | None:
    name = _clean_name(_cell(row, mapping.get("name")))
    value = _cell(row, mapping.get("value"))
    if not name or name in {"小结"} or value is None:
        return None
    ref_low, ref_high = _parse_reference(_cell(row, mapping.get("ref")))
    return {
        "panel": panel,
        "test_name": name,
        "value": value,
        "unit": _cell(row, mapping.get("unit")),
        "ref_low": ref_low,
        "ref_high": ref_high,
        "status": _status(value, _cell(row, mapping.get("status")), ref_low, ref_high),
        "source_file": source_file,
    }


def _colon_labs(panel: str, source_file: str, table: list[list[str]]) -> list[dict]:
    labs = []
    for row in table:
        if not row or (":" not in row[0] and "：" not in row[0]):
            continue
        name, value = re.split(r"[:：]", row[0], maxsplit=1)
        name = _clean_name(name)
        value = value.strip()
        ref_low = None
        ref_high = None
        if len(row) > 1 and "参考值" in row[1]:
            ref_text = re.sub(r"[()（）]", "", row[1]).replace("参考值", "")
            ref_text = ref_text.lstrip(":：").strip()
            ref_low, ref_high = _parse_reference(ref_text)
        if name and value:
            labs.append(
                {
                    "panel": panel,
                    "test_name": name,
                    "value": value,
                    "unit": None,
                    "ref_low": ref_low,
                    "ref_high": ref_high,
                    "status": _status(value, None, ref_low, ref_high),
                    "source_file": source_file,
                }
            )
    return labs


def _looks_like_continuation(table: list[list[str]], mapping: dict[str, int]) -> bool:
    if any(re.search(r"\d{4}\s*年", cell) for row in table[:3] for cell in row):
        return False
    if any(cell in {"单一感染（8种）", "混合感染（22种）"} for row in table[:2] for cell in row):
        return False
    first_data = next((row for row in table if len(row) > 1), None)
    if not first_data:
        return False
    required = [mapping.get("name"), mapping.get("value")]
    return all(index is not None and index < len(first_data) and first_data[index] for index in required)


def extract_labs(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    source_file = _project_path(path)
    labs: list[dict] = []
    previous_mapping: dict[str, int] | None = None
    previous_panel: str | None = None

    for table_index, match in enumerate(TABLE_RE.finditer(text), start=1):
        table = _parse_table(match.group(0))
        if not table:
            continue
        panel = _southgene_panel(path, table_index) or _nearest_panel(text[: match.start()], table)
        header_index = _header_index(table)

        if header_index is None:
            if previous_mapping and previous_panel and _looks_like_continuation(table, previous_mapping):
                for row in table:
                    lab = _lab(previous_panel, source_file, row, previous_mapping)
                    if lab:
                        labs.append(lab)
                continue
            labs.extend(_colon_labs(panel, source_file, table))
            continue

        header = table[header_index]
        if any(re.search(r"\d{4}\s*年", cell) for row in table[header_index + 1 : header_index + 3] for cell in row):
            continue
        mapping = _column_map(header)
        if "value" not in mapping and len(header) >= 2 and any("检测结果" in cell for cell in header):
            mapping = {"name": 0, "value": 1}
        if "name" not in mapping or "value" not in mapping:
            continue

        for row in table[header_index + 1 :]:
            lab = _lab(panel, source_file, row, mapping)
            if lab:
                labs.append(lab)

        previous_mapping = mapping
        previous_panel = panel

    return labs


def build_payload(path: Path, member_key: str) -> dict:
    visit_date = _date_from_name(path)
    org, _name, item = _title_parts(path)
    source_file = _project_path(path)
    pdf_path = PROJECT_DIR / "data" / "reports" / member_key / "pdf" / f"{path.stem}.pdf"

    if "南方基因" in path.name:
        visit = {
            "member_key": member_key,
            "date": visit_date,
            "type": "体检",
            "hospital": "南方基因 / 南京申友医学检验所",
            "department": "分子检测",
            "doctor": None,
            "chief_complaint": "生殖道微生态分子检测",
            "severity": "一般",
            "diagnosis": ["惰性乳杆菌主导"],
            "notes": "总体结果：惰性乳杆菌主导；乳酸菌比例81.78%。",
            "note_full": (
                "### 医生诊断\n"
                "惰性乳杆菌主导。\n\n"
                "### 诊疗意见\n"
                "生殖道微生态分子检测总体结果为惰性乳杆菌主导，乳酸菌比例81.78%。\n\n"
                "### 治疗方案说明\n"
                "报告中未提供具体用药或治疗方案。"
            ),
            "source_file": source_file,
        }
    elif existing := _load_existing_visit(member_key, visit_date):
        visit = {
            "member_key": member_key,
            "date": existing["date"],
            "type": existing["type"],
            "hospital": existing["hospital"],
            "department": existing["department"],
            "doctor": existing["doctor"],
            "chief_complaint": existing["chief_complaint"],
            "severity": existing["severity"],
            "diagnosis": _diagnosis(existing["diagnosis"]),
            "notes": existing["notes"] or f"{item}报告已归档，需根据报告补充关键摘要。",
            "note_full": existing["note_full"] or _default_note_full(item),
            "source_file": source_file,
        }
    else:
        visit = {
            "member_key": member_key,
            "date": visit_date,
            "type": "体检" if "体检" in item else "就医",
            "hospital": org,
            "department": None,
            "doctor": None,
            "chief_complaint": item,
            "severity": "一般",
            "diagnosis": [],
            "notes": f"{item}报告已归档，需根据报告补充关键摘要。",
            "note_full": _default_note_full(item),
            "source_file": source_file,
        }

    attachments = [
        {
            "title": f"{item} Markdown",
            "org": org,
            "tag": item,
            "filename": path.name,
            "file_path": source_file,
        }
    ]
    if pdf_path.exists():
        attachments.append(
            {
                "title": f"{item} PDF",
                "org": org,
                "tag": item,
                "filename": pdf_path.name,
                "file_path": _project_path(pdf_path),
            }
        )

    return {"visit": visit, "labs": extract_labs(path), "meds": [], "attachments": attachments}


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract report tables into visit import JSON payloads.")
    parser.add_argument("files", nargs="+", help="Markdown report files.")
    parser.add_argument("--member", default="chunzi", help="Member key.")
    parser.add_argument("--out-dir", required=True, help="Directory for generated JSON payloads.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for file in args.files:
        path = Path(file)
        payload = build_payload(path, args.member)
        out_path = out_dir / f"{path.stem}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append({"file": _project_path(out_path), "labs": len(payload["labs"])})
    print(json.dumps(written, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
