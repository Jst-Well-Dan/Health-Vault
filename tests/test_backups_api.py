import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("HEALTH_APP_PASSWORD", "test-family-password")
sys.path.insert(0, str(ROOT / "backend"))

import database  # noqa: E402
from database import init_db  # noqa: E402
from main import app  # noqa: E402
from routers.backups import create_backup, get_backups_info  # noqa: E402
from scripts.prune_old_backups import prune_old_backups  # noqa: E402


class BackupsApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "data" / "health.db"
        os.environ["HEALTH_VAULT_HOME"] = self.temp.name
        database.DB_PATH = self.db_path
        init_db()
        self.client = TestClient(app)
        self.client.post("/api/auth/login", json={"password": "test-family-password"})

    def tearDown(self):
        os.environ.pop("HEALTH_VAULT_HOME", None)
        self.temp.cleanup()

    def test_info_does_not_create_backup_dir_or_files(self):
        backup_dir = self.db_path.parent / "backups"
        self.assertFalse(backup_dir.exists())

        info = get_backups_info()

        self.assertEqual(info["database_path"], str(self.db_path))
        self.assertEqual(info["backup_dir"], str(backup_dir))
        self.assertFalse(info["exists"])
        self.assertEqual(info["backups"], [])
        self.assertFalse(backup_dir.exists())

    def test_post_creates_sqlite_backup_file(self):
        result = create_backup()
        backup_path = Path(result["backup_path"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["database_path"], str(self.db_path))
        self.assertEqual(backup_path.parent, self.db_path.parent / "backups")
        self.assertTrue(backup_path.is_file())
        self.assertEqual(backup_path.suffix, ".db")
        self.assertGreater(result["size_bytes"], 0)
        self.assertEqual(result["size_bytes"], backup_path.stat().st_size)
        self.assertIn("created_at", result)

        info = get_backups_info()
        self.assertTrue(info["exists"])
        self.assertEqual(len(info["backups"]), 1)
        self.assertEqual(info["backups"][0]["backup_path"], str(backup_path))

    def test_second_post_uses_distinct_filename(self):
        first = create_backup()
        second = create_backup()

        self.assertNotEqual(first["filename"], second["filename"])
        self.assertNotEqual(first["backup_path"], second["backup_path"])
        self.assertTrue(Path(first["backup_path"]).is_file())
        self.assertTrue(Path(second["backup_path"]).is_file())
        self.assertEqual(len(get_backups_info()["backups"]), 2)

    def test_validate_backup_success_returns_safe_metadata(self):
        backup = create_backup()

        response = self.client.post("/api/backups/validate", json={"filename": backup["filename"]})

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["filename"], backup["filename"])
        self.assertNotIn("backup_path", body)
        self.assertGreater(body["size_bytes"], 0)
        self.assertEqual(body["schema"]["integrity_check"], "ok")
        self.assertIn("members", body["schema"]["tables"])
        self.assertIn("user_version", body)

    def test_validate_rejects_corrupt_non_app_and_path_traversal(self):
        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True)
        (backup_dir / "corrupt.db").write_bytes(b"not sqlite")
        conn = sqlite3.connect(backup_dir / "other.db")
        try:
            conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
            conn.commit()
        finally:
            conn.close()

        cases = [
            ("corrupt.db", "损坏"),
            ("other.db", "缺少表"),
            ("../health.db", "单一数据库文件名"),
            (str(backup_dir / "other.db"), "单一数据库文件名"),
            ("notes.txt", ".db"),
            ("missing.db", "不存在"),
        ]
        for filename, message in cases:
            with self.subTest(filename=filename):
                response = self.client.post("/api/backups/validate", json={"filename": filename})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn(message, response.text)

    def test_prepare_restore_validates_and_creates_pre_restore_backup(self):
        selected = create_backup()

        response = self.client.post("/api/backups/prepare-restore", json={"filename": selected["filename"]})

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["database_path"], str(self.db_path))
        self.assertEqual(body["backup_dir"], str(self.db_path.parent / "backups"))
        self.assertEqual(body["selected_backup"]["filename"], selected["filename"])
        self.assertNotIn("backup_path", body["selected_backup"])
        pre_restore = body["pre_restore_backup"]
        self.assertTrue(pre_restore["filename"].startswith("health_prerestore_"))
        self.assertTrue((self.db_path.parent / "backups" / pre_restore["filename"]).is_file())
        self.assertTrue(self.db_path.is_file())

    def test_download_backup_returns_backup_file(self):
        backup = create_backup()

        response = self.client.get(f"/api/backups/download/{backup['filename']}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content[:16], b"SQLite format 3\x00")
        self.assertEqual(response.headers.get("content-type", "").split(";")[0], "application/octet-stream")

    def test_download_rejects_invalid_or_missing_backup(self):
        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True)
        (backup_dir / "notes.txt").write_bytes(b"x")
        for filename in ["missing.db", "notes.txt", "x.db"]:
            with self.subTest(filename=filename):
                response = self.client.get(f"/api/backups/download/{filename}")
                self.assertEqual(response.status_code, 400, response.text)

    def _imported_database_bytes(self) -> bytes:
        imported = Path(self.temp.name) / "imported.db"
        source = sqlite3.connect(self.db_path)
        destination = sqlite3.connect(imported)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        conn = sqlite3.connect(imported)
        try:
            conn.execute("INSERT INTO members (key, name) VALUES ('imported_member', '导入成员')")
            conn.commit()
        finally:
            conn.close()
        return imported.read_bytes()

    def test_import_switches_database_and_keeps_prerestore(self):
        content = self._imported_database_bytes()

        response = self.client.post(
            "/api/backups/import", files={"file": ("imported.db", content, "application/octet-stream")}
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["restart_required"])
        self.assertEqual(body["imported_filename"], "imported.db")
        self.assertEqual(body["database_path"], str(self.db_path))
        pre_restore = body["pre_restore_backup"]
        self.assertTrue(pre_restore["filename"].startswith("health_prerestore_"))
        self.assertTrue((self.db_path.parent / "backups" / pre_restore["filename"]).is_file())

        with database.get_conn() as conn:
            row = conn.execute("SELECT name FROM members WHERE key = 'imported_member'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "导入成员")

    def test_import_rejects_corrupt_empty_and_missing_tables(self):
        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True)
        only_one_table = Path(self.temp.name) / "partial.db"
        conn = sqlite3.connect(only_one_table)
        try:
            conn.execute("CREATE TABLE members (key TEXT PRIMARY KEY, name TEXT)")
            conn.commit()
        finally:
            conn.close()
        cases = [
            ("corrupt.db", b"not a sqlite database", "损坏"),
            ("notes.txt", b"any content", ".db"),
            ("empty.db", b"", "为空"),
            ("partial.db", only_one_table.read_bytes(), "缺少表"),
        ]
        for filename, content, message in cases:
            with self.subTest(filename=filename):
                response = self.client.post(
                    "/api/backups/import", files={"file": (filename, content, "application/octet-stream")}
                )
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn(message, response.text)
        # Failures must not replace the active database.
        with database.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM members").fetchone()[0], 0)

    def test_prune_old_backups_uses_active_database_backup_dir_and_dry_run(self):
        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True)
        old_db = backup_dir / "old.db"
        old_wal = backup_dir / "old.db-wal"
        new_db = backup_dir / "new.db"
        before_restore = backup_dir / "health.db.before_restore_20260803.db"
        unrelated = backup_dir / "notes.txt"
        recovery_dir = backup_dir / "restore-recovery"
        recovery_dir.mkdir()
        recovery_file = recovery_dir / "old.db"
        for path in [old_db, old_wal, new_db, before_restore, unrelated, recovery_file]:
            path.write_bytes(b"x")
        old_timestamp = time.time() - 10 * 86400
        for path in [old_db, old_wal, before_restore, unrelated, recovery_file]:
            os.utime(path, (old_timestamp, old_timestamp))

        dry_run = prune_old_backups(days=7, write=False)

        self.assertEqual(dry_run["mode"], "dry-run")
        self.assertEqual(dry_run["backup_dir"], str(backup_dir.resolve()))
        matched = {Path(item["path"]).name for item in dry_run["matched"]}
        self.assertEqual(matched, {"old.db", "old.db-wal"})
        self.assertEqual(dry_run["deleted"], [])
        self.assertTrue(old_db.exists())
        self.assertTrue(old_wal.exists())
        self.assertTrue(before_restore.exists())
        self.assertTrue(recovery_file.exists())

        written = prune_old_backups(days=7, write=True)

        self.assertEqual({Path(item["path"]).name for item in written["deleted"]}, {"old.db", "old.db-wal"})
        self.assertFalse(old_db.exists())
        self.assertFalse(old_wal.exists())
        self.assertTrue(new_db.exists())
        self.assertTrue(before_restore.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(recovery_file.exists())


if __name__ == "__main__":
    unittest.main()
