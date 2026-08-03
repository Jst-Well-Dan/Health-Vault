import json
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import quote


BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
PUBLIC_DIR = BASE_DIR / "data" / "public"
MOCK_DB_PATH = BASE_DIR / "data" / "mock" / "health_mock.db"
OUT_DIR = BASE_DIR / "docs" / "static-preview"
STATIC_ASSET_VERSION = "20260421-weight-row"

TABLES = {
    "members": "SELECT * FROM members ORDER BY sort_order, created_at, key",
    "visits": "SELECT * FROM visits ORDER BY date DESC, id DESC",
    "labs": "SELECT * FROM lab_results ORDER BY date DESC, id DESC",
    "meds": "SELECT * FROM meds ORDER BY ongoing DESC, COALESCE(start_date, '') DESC, id DESC",
    "weights": "SELECT * FROM weight_log ORDER BY date ASC, id ASC",
    "reminders": "SELECT * FROM reminders ORDER BY date ASC, id ASC",
    "attachments": "SELECT * FROM attachments ORDER BY date DESC, id DESC",
}


def _rows(conn: sqlite3.Connection, sql: str) -> list[dict]:
    return [dict(row) for row in conn.execute(sql).fetchall()]


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _avatar_url(member_key: str) -> str | None:
    if not PUBLIC_DIR.exists():
        return None
    key = (member_key or "").strip().lower()
    if not key:
        return None
    for path in sorted(PUBLIC_DIR.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"} and path.stem.lower() == key:
            return "public/" + quote(path.relative_to(PUBLIC_DIR).as_posix())
    return None


def _copytree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    if src.exists():
        shutil.copytree(src, dst)


def _copy_public_assets(dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    if not PUBLIC_DIR.exists():
        return
    for path in sorted(PUBLIC_DIR.iterdir()):
        if path.is_file() and (path.name == "README.md" or path.name.startswith("demo-")):
            shutil.copy2(path, dst / path.name)


def _write_index() -> None:
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="style.css?v=20260420-avatar">', f'<link rel="stylesheet" href="style.css?v={STATIC_ASSET_VERSION}">')
    html = html.replace('src="components/primitives.jsx?v=20260420-avatar"', f'src="components/primitives.jsx?v={STATIC_ASSET_VERSION}"')
    html = html.replace('src="components/screen_family.jsx?v=20260420-avatar"', f'src="components/screen_family.jsx?v={STATIC_ASSET_VERSION}"')
    html = html.replace('src="components/screen_member.jsx?v=20260420-avatar"', f'src="components/screen_member.jsx?v={STATIC_ASSET_VERSION}"')
    marker = '<script src="vendor/marked.min.js"></script>'
    html = html.replace(marker, marker + '\n<script src="static-api.js"></script>')
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")


def build_static_data() -> dict:
    if not MOCK_DB_PATH.exists():
        raise FileNotFoundError(f"Mock database not found: {MOCK_DB_PATH}")

    with sqlite3.connect(MOCK_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        data = {name: _rows(conn, sql) for name, sql in TABLES.items()}

    for member in data["members"]:
        member["allergies"] = _json_list(member.get("allergies"))
        member["chronic"] = _json_list(member.get("chronic"))
        member["avatar_url"] = _avatar_url(member.get("key", ""))

    for visit in data["visits"]:
        visit["diagnosis"] = _json_list(visit.get("diagnosis"))

    for med in data["meds"]:
        med["ongoing"] = bool(med.get("ongoing"))

    for reminder in data["reminders"]:
        reminder["done"] = bool(reminder.get("done"))

    attachment_text = {}
    exported_attachment_dir = OUT_DIR / "attachments"
    if exported_attachment_dir.exists():
        shutil.rmtree(exported_attachment_dir)
    exported_attachment_dir.mkdir(parents=True, exist_ok=True)
    for attachment in data["attachments"]:
        file_path = attachment.get("file_path")
        if not file_path:
            continue
        path = Path(file_path)
        resolved = path if path.is_absolute() else BASE_DIR / path
        if resolved.is_file():
            safe_name = f"{attachment['id']}-{resolved.name}"
            shutil.copy2(resolved, exported_attachment_dir / safe_name)
            attachment["static_url"] = "attachments/" + quote(safe_name)
        if resolved.suffix.lower() in {".md", ".txt", ".csv", ".json"} and resolved.is_file():
            attachment_text[str(attachment["id"])] = resolved.read_text(encoding="utf-8")

    data["attachment_text"] = attachment_text
    return data


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _copytree(FRONTEND_DIR / "components", OUT_DIR / "components")
    _copytree(FRONTEND_DIR / "vendor", OUT_DIR / "vendor")
    _copy_public_assets(OUT_DIR / "public")
    shutil.copy2(FRONTEND_DIR / "style.css", OUT_DIR / "style.css")
    shutil.copy2(FRONTEND_DIR / "static-api.js", OUT_DIR / "static-api.js")
    _write_index()

    data_dir = OUT_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "static-data.json").write_text(
        json.dumps(build_static_data(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Static preview exported to {OUT_DIR}")


if __name__ == "__main__":
    main()
