"""跨表检索与多指标趋势接口。"""

import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class SearchApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        import os

        os.environ["HEALTH_VAULT_HOME"] = self.temp.name
        os.environ["HEALTH_DB_PATH"] = str(Path(self.temp.name) / "health.db")
        import database
        from database import get_conn, init_db

        database.BASE_DIR = Path(self.temp.name).resolve()
        database.DB_PATH = database.BASE_DIR / "health.db"
        init_db()
        with get_conn() as conn:
            conn.execute("INSERT INTO members (key, name, full_name, allergies) VALUES ('dan', '东东', '段某', '青霉素')")
            conn.execute("INSERT INTO members (key, name) VALUES ('chun', '春春')")
            conn.execute(
                """
                INSERT INTO visits (member_key, date, type, hospital, department, chief_complaint, diagnosis, notes, note_full)
                VALUES ('dan', '2026-09-20', '就医', '安贞医院', '骨科', '运动后小腿疼痛', '["肌肉损伤"]', '建议休息', '### 医生诊断\n肌肉损伤')
                """
            )
            conn.execute(
                """
                INSERT INTO visits (member_key, date, type, hospital, chief_complaint, diagnosis, notes)
                VALUES ('chun', '2026-08-19', '体检', '瑞慈体检', '年度体检', '["甲状腺结节"]', '年度复查')
                """
            )
            conn.execute(
                """
                INSERT INTO lab_results (member_key, visit_id, date, panel, test_name, value, unit, ref_low, ref_high, status)
                VALUES ('chun', 2, '2026-08-19', '生化', '总胆固醇', '5.55', 'mmol/L', '0', '5.2', 'high')
                """
            )
            conn.execute(
                """
                INSERT INTO lab_results (member_key, visit_id, date, panel, test_name, value, unit, status)
                VALUES ('dan', 1, '2026-09-20', '心酶', '肌酸激酶', '1881', 'U/L', 'high')
                """
            )
            conn.execute("INSERT INTO meds (member_key, name, dose, freq, notes) VALUES ('dan', '布洛芬', '0.3g', 'bid', '饭后')")
            conn.execute("INSERT INTO attachments (member_key, visit_id, date, title, org, tag, filename, file_path, notes) VALUES ('chun', 2, '2026-08-19', '年度体检报告', '瑞慈体检', '体检报告', 'a.pdf', 'data/reports/chun/pdf/a.pdf', '含甲状腺超声')")
        from main import app

        self.client = TestClient(app)

    def tearDown(self):
        import os

        for key in ("HEALTH_VAULT_HOME", "HEALTH_DB_PATH"):
            os.environ.pop(key, None)
        self.temp.cleanup()

    def test_search_matches_across_tables_with_snippets(self):
        response = self.client.get("/api/records/search", params={"q": "甲状腺"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["total_hits"], 1)
        # 就诊记录里的诊断、附件备注都可能命中
        self.assertIn("visits", payload["results"])
        self.assertTrue(payload["results"]["attachments"] or payload["results"]["visits"])
        hit = next(row for group in payload["results"].values() for row in group)
        self.assertIn("snippet", hit)
        self.assertIn("matched_field", hit)

    def test_search_can_be_scoped_to_member_and_table(self):
        response = self.client.get("/api/records/search", params={"q": "体检", "member": "chun", "tables": "visits,attachments"})
        payload = response.json()
        self.assertEqual(set(payload["results"]), {"visits", "attachments"})
        for rows in payload["results"].values():
            for row in rows:
                self.assertEqual(row["member_key"], "chun")

    def test_search_rejects_unknown_table(self):
        response = self.client.get("/api/records/search", params={"q": "x", "tables": "sqlite_master"})
        self.assertEqual(response.status_code, 400)

    def test_search_truncates_long_text_fields(self):
        long_note = "很长" * 2000
        import database
        from database import get_conn

        with get_conn() as conn:
            conn.execute("UPDATE visits SET note_full = ? WHERE id = 1", (long_note,))
        payload = self.client.get("/api/records/search", params={"q": "很长", "tables": "visits"}).json()
        snippet = payload["results"]["visits"][0]["snippet"]
        self.assertLessEqual(len(snippet), 240)

    def test_lab_history_returns_multiple_series(self):
        response = self.client.get("/api/labs/history", params={"member": "chun", "tests": "总胆固醇,不存在的指标"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["counts"]["总胆固醇"], 1)
        self.assertEqual(payload["tests"]["总胆固醇"][0]["value"], "5.55")
        self.assertEqual(payload["missing"], ["不存在的指标"])

    def test_lab_history_is_case_insensitive_and_ordered(self):
        import database
        from database import get_conn

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO lab_results (member_key, visit_id, date, panel, test_name, value, unit, status)
                VALUES ('dan', 1, '2026-01-05', '心酶', 'CK', '100', 'U/L', 'normal')
                """
            )
            conn.execute(
                """
                INSERT INTO lab_results (member_key, visit_id, date, panel, test_name, value, unit, status)
                VALUES ('dan', 1, '2026-09-20', '心酶', 'CK', '1881', 'U/L', 'high')
                """
            )
        payload = self.client.get("/api/labs/history", params={"member": "dan", "tests": "ck"}).json()
        points = payload["tests"]["ck"]
        self.assertEqual([point["date"] for point in points], ["2026-01-05", "2026-09-20"])
        self.assertEqual(payload["canonical_names"]["ck"], "CK")

    def test_lab_history_rejects_empty_or_too_many_tests(self):
        self.assertEqual(self.client.get("/api/labs/history", params={"member": "dan", "tests": " , "}).status_code, 400)
        many = ",".join(f"t{i}" for i in range(25))
        self.assertEqual(self.client.get("/api/labs/history", params={"member": "dan", "tests": many}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
