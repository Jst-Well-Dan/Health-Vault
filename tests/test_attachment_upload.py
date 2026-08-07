import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("HEALTH_APP_PASSWORD", "test-family-password")
sys.path.insert(0, str(ROOT / "backend"))

import database  # noqa: E402
from database import get_conn, init_db  # noqa: E402
from main import app  # noqa: E402
from routers import attachments as attachments_router  # noqa: E402


class AttachmentUploadTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "data" / "health.db"
        os.environ["HEALTH_VAULT_HOME"] = self.temp.name
        database.DB_PATH = self.db_path
        init_db()
        with get_conn() as conn:
            conn.execute("INSERT INTO members (key, name, species) VALUES ('self', '本人', 'human')")
            conn.execute("INSERT INTO members (key, name, species) VALUES ('pet', '小猫', 'cat')")
            cur = conn.execute("INSERT INTO visits (member_key, date, type) VALUES ('self', '2026-08-03', '就医')")
            self.visit_id = cur.lastrowid
            other = conn.execute("INSERT INTO visits (member_key, date, type) VALUES ('pet', '2026-08-03', '就医')")
            self.other_visit_id = other.lastrowid
        self.client = TestClient(app)
        self.client.post("/api/auth/login", json={"password": "test-family-password"})

    def tearDown(self):
        os.environ.pop("HEALTH_VAULT_HOME", None)
        self.temp.cleanup()

    def _upload(self, filename="report.pdf", content=b"hello", data=None):
        payload = {
            "member_key": "self",
            "date": "2026-08-04",
            "title": "普通附件",
        }
        if data:
            payload.update(data)
        return self.client.post(
            "/api/attachments/upload",
            data=payload,
            files={"file": (filename, content, "application/octet-stream")},
        )

    def test_upload_attachment_success_with_visit(self):
        response = self._upload(
            filename="../门诊发票.pdf",
            content=b"pdf-content",
            data={"visit_id": str(self.visit_id), "org": "社区医院", "tag": "发票", "notes": "仅归档"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["member_key"], "self")
        self.assertEqual(body["visit_id"], self.visit_id)
        self.assertEqual(body["title"], "普通附件")
        self.assertEqual(body["filename"], "门诊发票.pdf")
        stored = self.db_path.parent.parent / body["file_path"]
        self.assertTrue(stored.is_file())
        self.assertEqual(stored.read_bytes(), b"pdf-content")
        self.assertIn("attachments/self/", body["file_path"].replace("\\", "/"))

    def test_upload_rejects_missing_member_and_visit_mismatch(self):
        missing = self._upload(data={"member_key": "missing"})
        self.assertEqual(missing.status_code, 404)
        self.assertIn("成员不存在", missing.text)

        mismatch = self._upload(data={"visit_id": str(self.other_visit_id)})
        self.assertEqual(mismatch.status_code, 422)
        self.assertIn("不属于当前成员", mismatch.text)

    def test_upload_rejects_unknown_extension_and_empty_file(self):
        bad_ext = self._upload(filename="script.exe")
        self.assertEqual(bad_ext.status_code, 400)
        self.assertIn("不支持", bad_ext.text)

        empty = self._upload(filename="empty.pdf", content=b"")
        self.assertEqual(empty.status_code, 400)
        self.assertIn("文件为空", empty.text)

    def test_db_failure_cleans_saved_file(self):
        original = attachments_router._insert_attachment_row

        def fail_insert(payload):
            raise RuntimeError("forced db failure")

        attachments_router._insert_attachment_row = fail_insert
        try:
            with self.assertRaises(RuntimeError):
                self._upload(filename="cleanup.pdf", content=b"will be removed")
        finally:
            attachments_router._insert_attachment_row = original

        upload_dir = self.db_path.parent / "attachments" / "self"
        leftovers = list(upload_dir.glob("*")) if upload_dir.exists() else []
        self.assertEqual(leftovers, [])

    def test_patch_attachment_metadata_updates_safe_fields_and_keeps_file(self):
        uploaded = self._upload(filename="edit.pdf", content=b"original bytes").json()
        stored = self.db_path.parent.parent / uploaded["file_path"]
        self.assertTrue(stored.is_file())

        response = self.client.patch(
            f"/api/attachments/{uploaded['id']}",
            json={
                "date": "2026-08-05",
                "title": "已编辑附件",
                "org": "新机构",
                "tag": "影像",
                "notes": "只改元数据",
                "visit_id": self.visit_id,
                "filename": "should-not-change.pdf",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["date"], "2026-08-05")
        self.assertEqual(body["title"], "已编辑附件")
        self.assertEqual(body["org"], "新机构")
        self.assertEqual(body["tag"], "影像")
        self.assertEqual(body["notes"], "只改元数据")
        self.assertEqual(body["visit_id"], self.visit_id)
        self.assertEqual(body["filename"], uploaded["filename"])
        self.assertEqual(body["file_path"], uploaded["file_path"])
        self.assertEqual(stored.read_bytes(), b"original bytes")

    def test_patch_attachment_rejects_cross_member_visit_link(self):
        uploaded = self._upload(filename="mismatch.pdf", content=b"safe").json()
        stored = self.db_path.parent.parent / uploaded["file_path"]

        response = self.client.patch(
            f"/api/attachments/{uploaded['id']}",
            json={"visit_id": self.other_visit_id},
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("关联就诊记录不属于当前成员", response.text)
        self.assertTrue(stored.is_file())
        self.assertEqual(stored.read_bytes(), b"safe")
        with get_conn() as conn:
            row = conn.execute("SELECT visit_id, file_path FROM attachments WHERE id = ?", (uploaded["id"],)).fetchone()
        self.assertIsNone(row["visit_id"])
        self.assertEqual(row["file_path"], uploaded["file_path"])

    def test_delete_attachment_metadata_keeps_file_by_default(self):
        uploaded = self._upload(filename="keep.pdf", content=b"keep me").json()
        stored = self.db_path.parent.parent / uploaded["file_path"]
        self.assertTrue(stored.is_file())

        response = self.client.delete(f"/api/attachments/{uploaded['id']}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": True, "file_deleted": False})
        self.assertTrue(stored.is_file())
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM attachments WHERE id = ?", (uploaded["id"],)).fetchone()
        self.assertIsNone(row)

    def test_delete_attachment_with_file_removes_safe_stored_file(self):
        uploaded = self._upload(filename="remove.pdf", content=b"delete me").json()
        stored = self.db_path.parent.parent / uploaded["file_path"]
        self.assertTrue(stored.is_file())

        response = self.client.delete(f"/api/attachments/{uploaded['id']}?delete_file=true")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": True, "file_deleted": True})
        self.assertFalse(stored.exists())
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM attachments WHERE id = ?", (uploaded["id"],)).fetchone()
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
