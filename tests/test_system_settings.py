import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class SystemSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["HEALTH_VAULT_HOME"] = self.temp.name
        os.environ["HEALTH_DB_PATH"] = str(Path(self.temp.name) / "health.db")
        os.environ["HEALTH_DISABLE_AGENT_RUNTIME"] = "1"
        import database
        database.BASE_DIR = Path(self.temp.name)
        database.DB_PATH = Path(self.temp.name) / "health.db"
        from services import system_settings
        system_settings.invalidate_cache()
        from main import app
        self.app = app

    def tearDown(self):
        for key in ("HEALTH_VAULT_HOME", "HEALTH_DB_PATH", "HEALTH_DISABLE_AGENT_RUNTIME", "HEALTH_HOST"):
            os.environ.pop(key, None)
        self.temp.cleanup()

    def test_mineru_status_returns_only_safe_token_state(self):
        version = subprocess.CompletedProcess(["mineru-open-api", "version"], 0, stdout="mineru-open-api version v0.5.3\n")
        auth_show = subprocess.CompletedProcess(["mineru-open-api", "auth", "--show"], 0, stdout="Token source: config\nToken: private-value\n")
        with TestClient(self.app) as client:
            with patch("services.mineru.command_path", return_value="/test/mineru-open-api"), patch("services.mineru._managed_token", return_value=None), patch("services.mineru.subprocess.run", side_effect=[version, auth_show]):
                response = client.get("/api/settings/mineru")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"installed": True, "version": "v0.5.3", "token_configured": True, "token_source": "mineru_cli", "secure_storage_available": True, "mode": "flash"})
        self.assertNotIn("private-value", response.text)

    def test_mineru_token_can_be_saved_from_any_session_and_never_returned(self):
        token = "token-that-must-never-appear-in-a-response"
        safe_status = {"installed": True, "version": "v0.5.3", "token_configured": True, "token_source": "health_vault", "secure_storage_available": True, "mode": "flash"}
        with TestClient(self.app) as client:
            with patch("routers.settings.mineru.save_managed_token") as save_token, patch("routers.settings.mineru.verify_managed_token", return_value=True), patch("routers.settings.mineru.status", return_value=safe_status):
                response = client.post("/api/settings/mineru/token", json={"token": token})
        self.assertEqual(response.status_code, 200)
        save_token.assert_called_once_with(token)
        self.assertEqual(response.json(), safe_status)
        self.assertNotIn(token, response.text)

    def test_mineru_token_endpoints_are_available_without_login(self):
        # 本机无鉴权：接口直接可用，但仍不得回显 token。
        with TestClient(self.app) as client:
            with patch("routers.settings.mineru.save_managed_token") as save_token, patch("routers.settings.mineru.verify_managed_token", return_value=True), patch("routers.settings.mineru.status", return_value={"token_configured": True}):
                response = client.post("/api/settings/mineru/token", json={"token": "a" * 16})
        self.assertEqual(response.status_code, 200)
        save_token.assert_called_once()

    def test_resolved_host_prefers_env_over_file(self):
        from services import system_settings
        system_settings.save_settings({"host": "100.90.80.70"})
        self.assertEqual(system_settings.resolved_host(), "100.90.80.70")
        os.environ["HEALTH_HOST"] = "127.0.0.1"
        self.assertEqual(system_settings.resolved_host(), "127.0.0.1")

    def test_detect_tailscale_missing_binary(self):
        from services import system_settings
        with patch("shutil.which", return_value=None), patch("platform.system", return_value="Linux"):
            result = system_settings.detect_tailscale()
        self.assertEqual(result, {"installed": False, "connected": False, "ip": None})
        with patch("services.system_settings.detect_tailscale", return_value={"installed": True, "connected": True, "ip": "100.90.80.70"}):
            self.assertEqual(system_settings.tailscale_bind_host(), "100.90.80.70")
        with patch("services.system_settings.detect_tailscale", return_value={"installed": True, "connected": False, "ip": None}):
            self.assertIsNone(system_settings.tailscale_bind_host())

    def test_remote_access_tailscale_only(self):
        # Tailscale-only：有 100.x 才放行，无连接仍拒绝，关闭切回本机。
        from services import system_settings
        with TestClient(self.app) as client:
            with patch("services.system_settings.tailscale_bind_host", return_value="100.90.80.70"):
                ok = client.post("/api/settings/host", json={"enable_remote": True})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.json()["host"], "100.90.80.70")
            self.assertEqual(system_settings.load_settings()["host"], "100.90.80.70")
            with patch("services.system_settings.tailscale_bind_host", return_value=None):
                refused = client.post("/api/settings/host", json={"enable_remote": True})
            self.assertEqual(refused.status_code, 409)
            off = client.post("/api/settings/host", json={"enable_remote": False})
            self.assertEqual(off.status_code, 200)
            self.assertEqual(off.json()["host"], "127.0.0.1")

    def test_resolve_bind_host_with_heal_local(self):
        from services import system_settings
        with patch("services.system_settings.tailscale_bind_host", return_value=None):
            host, warning = system_settings.resolve_bind_host_with_heal()
        self.assertEqual((host, warning), ("127.0.0.1", None))

    def test_resolve_bind_host_with_heal_keeps_matching_tailscale_ip(self):
        from services import system_settings
        system_settings.save_settings({"host": "100.1.2.3"})
        with patch("services.system_settings.tailscale_bind_host", return_value="100.1.2.3"):
            host, warning = system_settings.resolve_bind_host_with_heal()
        self.assertEqual((host, warning), ("100.1.2.3", None))

    def test_resolve_bind_host_with_heal_rewrites_stale_ip(self):
        from services import system_settings
        system_settings.save_settings({"host": "100.1.2.3"})
        with patch("services.system_settings.tailscale_bind_host", return_value="100.4.5.6"):
            host, warning = system_settings.resolve_bind_host_with_heal()
        self.assertEqual(host, "100.4.5.6")
        self.assertIn("100.4.5.6", warning or "")
        self.assertEqual(system_settings.load_settings()["host"], "100.4.5.6")

    def test_resolve_bind_host_with_heal_falls_back_but_keeps_remote_config(self):
        from services import system_settings
        system_settings.save_settings({"host": "100.1.2.3"})
        with patch("services.system_settings.tailscale_bind_host", return_value=None):
            host, warning = system_settings.resolve_bind_host_with_heal()
        self.assertEqual(host, "127.0.0.1")
        self.assertIn("一键重启", warning or "")
        self.assertEqual(system_settings.load_settings()["host"], "100.1.2.3")  # kept for a later restart

    def test_resolve_bind_host_with_heal_never_rewrites_env_host(self):
        from services import system_settings
        os.environ["HEALTH_HOST"] = "100.9.9.9"
        system_settings.save_settings({"host": "100.1.2.3"})
        try:
            with patch("services.system_settings.tailscale_bind_host", return_value="100.4.5.6"):
                host, warning = system_settings.resolve_bind_host_with_heal()
        finally:
            os.environ.pop("HEALTH_HOST", None)
        self.assertEqual(host, "100.9.9.9")
        self.assertIn("HEALTH_HOST", warning or "")
        self.assertEqual(system_settings.load_settings()["host"], "100.1.2.3")

    def test_tailscale_ip_range_check(self):
        from services import system_settings
        for host in ("100.64.0.1", "100.90.80.70", "100.126.18.110", "100.127.255.255"):
            self.assertTrue(system_settings.is_tailscale_ip(host), host)
            self.assertTrue(system_settings.is_allowed_bind_host(host), host)
        for host in ("0.0.0.0", "127.0.0.1", "192.168.1.10", "100.63.1.1", "100.128.0.1", "8.8.8.8", None, ""):
            self.assertFalse(system_settings.is_tailscale_ip(host), host)
        self.assertTrue(system_settings.is_allowed_bind_host("127.0.0.1"))
        self.assertFalse(system_settings.is_allowed_bind_host("0.0.0.0"))
        self.assertFalse(system_settings.is_allowed_bind_host("192.168.1.10"))

    def test_bind_warning_surfaced_in_system_settings(self):
        with TestClient(self.app) as client:
            response = client.get("/api/settings/system")
            self.assertIsNone(response.json().get("bind_warning"))
            os.environ["HEALTH_BOUND_WARNING"] = "Tailscale 未连接，暂以本机模式启动"
            try:
                response = client.get("/api/settings/system")
            finally:
                os.environ.pop("HEALTH_BOUND_WARNING", None)
            self.assertEqual(response.json()["bind_warning"], "Tailscale 未连接，暂以本机模式启动")

    def test_restart_endpoint_triggers_lifecycle_restart(self):
        with TestClient(self.app) as client:
            with patch("lifecycle.request_restart", return_value=4242) as request_restart:
                response = client.post("/api/settings/restart")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)
        self.assertEqual(response.json()["pid"], 4242)
        self.assertEqual(response.json()["pending_host"], "127.0.0.1")
        request_restart.assert_called_once_with()

    def test_restart_endpoint_is_registered(self):
        with TestClient(self.app) as client:
            paths = client.get("/openapi.json").json()["paths"]
        self.assertIn("/api/settings/restart", paths)
        self.assertIn("/api/settings/system", paths)
        self.assertNotIn("/api/settings/password", paths)  # 登录鉴权已取消

    def test_windows_autostart_script_allows_empty_standard_output(self):
        from services import system_settings
        completed = subprocess.CompletedProcess(["powershell"], 0, stdout=None, stderr=None)
        script = system_settings._WINDOWS_SCRIPTS_DIR / "remove-autostart.ps1"
        self.assertTrue(script.is_file())
        with patch("services.system_settings.subprocess.run", return_value=completed):
            self.assertEqual(system_settings._run_script(script), {"ok": True, "message": ""})

    def test_autostart_script_resources_exist(self):
        from services import system_settings
        for script in (
            system_settings._WINDOWS_SCRIPTS_DIR / "setup-autostart.ps1",
            system_settings._WINDOWS_SCRIPTS_DIR / "start-hidden.ps1",
            system_settings._WINDOWS_SCRIPTS_DIR / "remove-autostart.ps1",
            system_settings._MACOS_SCRIPTS_DIR / "setup-autostart.sh",
            system_settings._MACOS_SCRIPTS_DIR / "start-launchagent.sh",
            system_settings._MACOS_SCRIPTS_DIR / "remove-autostart.sh",
        ):
            self.assertTrue(script.is_file(), script)


if __name__ == "__main__":
    unittest.main()
