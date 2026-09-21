"""本机直连模式：没有登录鉴权，但只允许监听 127.0.0.1。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class LocalAccessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["HEALTH_VAULT_HOME"] = self.temp.name
        os.environ["HEALTH_DB_PATH"] = str(Path(self.temp.name) / "health.db")
        os.environ["HEALTH_DISABLE_AGENT_RUNTIME"] = "1"
        os.environ.pop("HEALTH_BOUND_HOST", None)
        import database
        from database import init_db
        database.BASE_DIR = Path(self.temp.name).resolve()
        database.DB_PATH = database.BASE_DIR / "health.db"
        init_db()
        from services import system_settings
        system_settings.invalidate_cache()
        from main import app
        self.app = app

    def tearDown(self):
        for key in ("HEALTH_VAULT_HOME", "HEALTH_DB_PATH", "HEALTH_DISABLE_AGENT_RUNTIME", "HEALTH_BOUND_HOST"):
            os.environ.pop(key, None)
        self.temp.cleanup()

    def test_api_is_reachable_without_any_credential(self):
        client = TestClient(self.app)
        self.assertEqual(client.get("/api/meta").status_code, 200)
        self.assertEqual(client.get("/api/members").status_code, 200)
        self.assertEqual(client.get("/style.css").status_code, 200)
        self.assertEqual(client.get("/").status_code, 200)

    def test_login_endpoints_are_gone(self):
        client = TestClient(self.app)
        for path in ("/login", "/api/auth/status", "/api/auth/login", "/api/auth/setup", "/api/settings/password"):
            with self.subTest(path=path):
                self.assertIn(client.get(path).status_code, {404, 405})

    def test_system_settings_no_longer_reports_a_password_source(self):
        client = TestClient(self.app)
        payload = client.get("/api/settings/system").json()
        self.assertNotIn("password_source", payload)
        self.assertNotIn("trust_localhost", payload)


class BindGuardTest(unittest.TestCase):
    def test_only_loopback_binds_are_allowed(self):
        import run_backend

        for host in ("127.0.0.1", "::1", "localhost"):
            with self.subTest(host=host):
                self.assertIsNone(run_backend.bind_guard_error(host))
        for host in ("0.0.0.0", "100.101.102.103", "192.168.1.10"):
            with self.subTest(host=host):
                self.assertIn("拒绝启动", run_backend.bind_guard_error(host) or "")


if __name__ == "__main__":
    unittest.main()
