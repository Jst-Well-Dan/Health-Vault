"""Tailscale-only 模式：没有登录鉴权，只允许监听 127.0.0.1 或 Tailscale 100.x。"""

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class LocalAccessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["HEALTH_VAULT_HOME"] = self.temp.name
        os.environ["HEALTH_DB_PATH"] = str(Path(self.temp.name) / "health.db")
        os.environ["HEALTH_DISABLE_AGENT_RUNTIME"] = "1"
        os.environ.pop("HEALTH_BOUND_HOSTS", None)
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
        for key in ("HEALTH_VAULT_HOME", "HEALTH_DB_PATH", "HEALTH_DISABLE_AGENT_RUNTIME", "HEALTH_BOUND_HOSTS", "HEALTH_BOUND_HOST"):
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


class DualListenStartupTest(unittest.TestCase):
    """一个进程监听多个地址时，lifespan 会跑多次；启动副作用必须只跑一次。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["HEALTH_VAULT_HOME"] = self.temp.name
        os.environ["HEALTH_DB_PATH"] = str(Path(self.temp.name) / "health.db")
        os.environ["HEALTH_DISABLE_AGENT_RUNTIME"] = "1"
        os.environ.pop("HEALTH_MOCK_MODE", None)
        import database

        database.BASE_DIR = Path(self.temp.name).resolve()
        database.DB_PATH = database.BASE_DIR / "health.db"

    def tearDown(self):
        for key in ("HEALTH_VAULT_HOME", "HEALTH_DB_PATH", "HEALTH_DISABLE_AGENT_RUNTIME"):
            os.environ.pop(key, None)
        self.temp.cleanup()

    def test_concurrent_startup_on_fresh_database_does_not_raise(self):
        import main

        errors: list[BaseException] = []

        def run_startup() -> None:
            try:
                main.startup()
            except BaseException as exc:  # 唯一的失败原因就是并发抢 WAL 锁
                errors.append(exc)

        threads = [threading.Thread(target=run_startup) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual([type(exc).__name__ for exc in errors], [])

    def test_startup_side_effects_run_once_per_database(self):
        import main

        main.startup()
        with patch("main.init_db") as init_db_mock, patch("main.seed_mock_data") as seed_mock:
            main.startup()
        self.assertEqual(init_db_mock.call_count, 0)
        self.assertEqual(seed_mock.call_count, 0)


class BindGuardTest(unittest.TestCase):
    def test_only_loopback_and_tailscale_binds_are_allowed(self):
        import run_backend

        for host in ("127.0.0.1", "::1", "localhost", "100.101.102.103", "100.126.18.110"):
            with self.subTest(host=host):
                self.assertIsNone(run_backend.bind_guard_error(host))
        for host in ("0.0.0.0", "::", "192.168.1.10", "10.0.0.5", "8.8.8.8", "100.63.1.1", "100.128.0.1"):
            with self.subTest(host=host):
                self.assertIn("拒绝启动", run_backend.bind_guard_error(host) or "")


class PortCheckTest(unittest.TestCase):
    def test_free_port_has_no_conflict(self):
        import run_backend

        self.assertIsNone(run_backend.port_conflict_error("127.0.0.1", 0))

    def test_occupied_port_reports_conflict(self):
        import run_backend
        import socket

        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        try:
            msg = run_backend.port_conflict_error("127.0.0.1", holder.getsockname()[1])
        finally:
            holder.close()
        self.assertIn("端口被占用", msg or "")


if __name__ == "__main__":
    unittest.main()
