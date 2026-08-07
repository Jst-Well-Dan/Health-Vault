import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class WebAuthTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["HEALTH_VAULT_HOME"] = self.temp.name
        os.environ["HEALTH_DB_PATH"] = str(Path(self.temp.name) / "health.db")
        os.environ["HEALTH_APP_PASSWORD"] = "test-family-password"
        os.environ["HEALTH_DISABLE_AGENT_RUNTIME"] = "1"
        import database
        database.DB_PATH = Path(self.temp.name) / "health.db"
        from main import app
        self.app = app

    def tearDown(self):
        for key in ("HEALTH_VAULT_HOME", "HEALTH_DB_PATH", "HEALTH_APP_PASSWORD", "HEALTH_DISABLE_AGENT_RUNTIME"):
            os.environ.pop(key, None)
        self.temp.cleanup()

    def test_protects_app_then_issues_http_only_session(self):
        with TestClient(self.app) as client:
            denied = client.get("/api/meta")
            self.assertEqual(denied.status_code, 401)
            login = client.post("/api/auth/login", json={"password": "test-family-password"})
            self.assertEqual(login.status_code, 200)
            self.assertIn("HttpOnly", login.headers["set-cookie"])
            self.assertEqual(client.get("/api/meta").status_code, 200)
            self.assertEqual(client.post("/api/auth/logout").status_code, 200)
            self.assertEqual(client.get("/api/meta").status_code, 401)

    def test_rejects_wrong_password(self):
        with TestClient(self.app) as client:
            self.assertEqual(client.post("/api/auth/login", json={"password": "wrong"}).status_code, 401)

    def test_empty_agent_secret_is_regenerated_not_treated_as_authentication(self):
        import agent_runtime
        secret_path = Path(self.temp.name) / "data" / "agent-runtime-secret.bin"
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        secret_path.write_text("   ", encoding="utf-8")
        agent_runtime._secret = None
        with TestClient(self.app) as client:
            self.assertEqual(client.get("/api/meta").status_code, 401)
        self.assertTrue(secret_path.read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    unittest.main()
