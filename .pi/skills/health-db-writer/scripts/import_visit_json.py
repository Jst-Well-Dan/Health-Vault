import runpy
from pathlib import Path
import sys


def main() -> None:
    skill_dir = Path(__file__).resolve().parents[1]
    project_dir = skill_dir.parents[1]
    script_path = project_dir / "backend" / "scripts" / "import_visit_json.py"
    if not script_path.exists():
        raise SystemExit(f"Project import script not found: {script_path}")
    sys.path.insert(0, str(script_path.parent))
    sys.argv[0] = str(script_path)
    runpy.run_path(str(script_path), run_name="__main__")


if __name__ == "__main__":
    main()
