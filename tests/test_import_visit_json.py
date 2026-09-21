"""写入脚本的安全边界：dry-run 不写库、写入前备份、附件缺失/重复就诊要拒绝。"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

import database  # noqa: E402
import import_visit_json as writer  # noqa: E402


def payload(**overrides) -> dict:
    data = {
        "visit": {
            "member_key": "dan",
            "date": "2026-09-20",
            "type": "就医",
            "hospital": "安贞医院",
            "chief_complaint": "运动后小腿疼痛",
            "severity": "一般",
            "diagnosis": ["肌肉损伤"],
            "notes": "建议休息两周",
            "note_full": "### 医生诊断\n肌肉损伤",
            "source_file": "data/reports/dan/md/20260920_安贞医院_运动后小腿疼痛_东东.md",
        },
        "labs": [{"panel": "心酶", "test_name": "肌酸激酶", "value": "1881", "unit": "U/L", "status": "high"}],
        "meds": [{"name": "布洛芬", "dose": "0.3g", "freq": "bid", "start_date": "2026-09-20"}],
        "attachments": [],
    }
    data.update(overrides)
    return data


class ImportVisitJsonTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["HEALTH_VAULT_HOME"] = self.temp.name
        os.environ["HEALTH_DB_PATH"] = str(Path(self.temp.name) / "health.db")
        database.BASE_DIR = Path(self.temp.name).resolve()
        database.DB_PATH = database.BASE_DIR / "health.db"
        database.init_db()
        with database.get_conn() as conn:
            conn.execute("INSERT INTO members (key, name) VALUES ('dan', '东东')")
        self.payload_path = Path(self.temp.name) / "payload.json"

    def tearDown(self):
        for key in ("HEALTH_VAULT_HOME", "HEALTH_DB_PATH"):
            os.environ.pop(key, None)
        self.temp.cleanup()

    def write_payload(self, data: dict) -> None:
        self.payload_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def run_cli(self, *extra: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = writer.main(["--file", str(self.payload_path), *extra])
        return code, stdout.getvalue(), stderr.getvalue()

    def counts(self) -> dict:
        with database.get_conn() as conn:
            return {
                "visits": conn.execute("SELECT COUNT(*) AS c FROM visits").fetchone()["c"],
                "labs": conn.execute("SELECT COUNT(*) AS c FROM lab_results").fetchone()["c"],
                "meds": conn.execute("SELECT COUNT(*) AS c FROM meds").fetchone()["c"],
            }

    def test_dry_run_writes_nothing(self):
        self.write_payload(payload())
        code, stdout, _stderr = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("[dry-run]", stdout)
        self.assertIn("东东", stdout)
        self.assertEqual(self.counts(), {"visits": 0, "labs": 0, "meds": 0})

    def test_write_creates_backup_and_verifies_counts(self):
        self.write_payload(payload())
        code, stdout, _stderr = self.run_cli("--write")
        self.assertEqual(code, 0)
        self.assertIn("已写入 visit_id=", stdout)
        self.assertIn("备份：", stdout)
        self.assertEqual(self.counts(), {"visits": 1, "labs": 1, "meds": 1})
        backups = list((database.BASE_DIR / "backups").glob("health_*.db"))
        self.assertEqual(len(backups), 1)

    def test_missing_attachment_file_is_rejected(self):
        self.write_payload(payload(attachments=[{"title": "报告", "file_path": "data/reports/dan/pdf/不存在.pdf"}]))
        code, _stdout, stderr = self.run_cli("--write")
        self.assertEqual(code, 1)
        self.assertIn("附件文件不存在", stderr)
        self.assertEqual(self.counts()["visits"], 0)

    def test_unknown_member_is_rejected(self):
        data = payload()
        data["visit"]["member_key"] = "nobody"
        self.write_payload(data)
        code, _stdout, stderr = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("成员不存在", stderr)

    def test_bad_date_and_severity_are_rejected(self):
        data = payload()
        data["visit"]["date"] = "2026/09/20"
        self.write_payload(data)
        self.assertEqual(self.run_cli()[0], 1)

        data = payload()
        data["visit"]["severity"] = "很严重"
        self.write_payload(data)
        code, _stdout, stderr = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("severity", stderr)

    def test_empty_summary_fields_are_rejected(self):
        data = payload()
        data["visit"]["notes"] = "  "
        self.write_payload(data)
        code, _stdout, stderr = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("note_full", stderr)

    def test_duplicate_visit_needs_explicit_flag(self):
        self.write_payload(payload())
        self.assertEqual(self.run_cli("--write")[0], 0)
        code, _stdout, stderr = self.run_cli("--write")
        self.assertEqual(code, 1)
        self.assertIn("--allow-duplicate", stderr)
        self.assertEqual(self.counts()["visits"], 1)
        self.assertEqual(self.run_cli("--write", "--allow-duplicate")[0], 0)
        self.assertEqual(self.counts()["visits"], 2)

    def test_member_can_be_overridden_from_cli(self):
        data = payload()
        del data["visit"]["member_key"]
        self.write_payload(data)
        self.assertEqual(self.run_cli()[0], 1)
        code, stdout, _stderr = self.run_cli("--member", "dan")
        self.assertEqual(code, 0)
        self.assertIn("东东", stdout)

    def test_json_output_carries_paths_for_scripts(self):
        self.write_payload(payload())
        code, stdout, _stderr = self.run_cli("--write", "--json")
        self.assertEqual(code, 0)
        result = json.loads(stdout.strip().splitlines()[-1])
        self.assertTrue(result["ok"])
        self.assertEqual(result["visit_id"], 1)
        self.assertIn("backup_path", result)


if __name__ == "__main__":
    unittest.main()
