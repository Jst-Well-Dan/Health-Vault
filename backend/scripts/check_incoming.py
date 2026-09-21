"""检查 `incoming/` 里的报告是否都已归档到 `data/reports/`。

报告导入完成后，`incoming/` 里的原件就是冗余副本。这个脚本按内容 md5 比对，
只删除**确认已归档**的文件，避免误删还没导入的报告。

用法::

    python backend/scripts/check_incoming.py                 # 只报告状态
    python backend/scripts/check_incoming.py --delete-archived   # 删除已归档的原件
"""

import argparse
import hashlib
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent

INCOMING_DIR = PROJECT_DIR / "incoming"
ARCHIVE_DIR = PROJECT_DIR / "data" / "reports"
ARCHIVE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    if not ARCHIVE_DIR.is_dir():
        return index
    for path in ARCHIVE_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in ARCHIVE_SUFFIXES:
            index.setdefault(md5(path), path)
    return index


def scan() -> list[tuple[Path, Path | None]]:
    if not INCOMING_DIR.is_dir():
        return []
    index = archive_index()
    results = []
    for path in sorted(item for item in INCOMING_DIR.rglob("*") if item.is_file()):
        results.append((path, index.get(md5(path))))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 incoming/ 里哪些报告已经归档")
    parser.add_argument("--delete-archived", action="store_true", help="删除已确认归档的原件")
    args = parser.parse_args(argv)

    results = scan()
    if not results:
        print(f"incoming/ 里没有待处理文件：{INCOMING_DIR}")
        return 0

    archived = [(path, hit) for path, hit in results if hit]
    pending = [path for path, hit in results if not hit]

    for path, hit in archived:
        print(f"[已归档] {path.relative_to(PROJECT_DIR)} → {hit.relative_to(PROJECT_DIR)}")
    for path in pending:
        print(f"[待导入] {path.relative_to(PROJECT_DIR)}")

    print(f"\n合计 {len(results)} 个文件：已归档 {len(archived)}、待导入 {len(pending)}")

    if args.delete_archived and archived:
        for path, _hit in archived:
            path.unlink()
        for folder in sorted({path.parent for path, _ in archived}, key=lambda item: -len(item.parts)):
            if folder != INCOMING_DIR and folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        print(f"已删除 {len(archived)} 个已归档原件（归档副本保留在 data/reports/）。")

    if pending and args.delete_archived:
        print("仍有未归档文件，未删除任何内容以外的文件；先完成导入再重跑。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
