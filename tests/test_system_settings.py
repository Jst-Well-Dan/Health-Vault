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
        os.environ["HEALTH_APP_PASSWORD"] = "test-family-password"
        os.environ["HEALTH_DISABLE_AGENT_RUNTIME"] = "1"
        import database
        database.BASE_DIR = Path(self.temp.name)
        database.DB_PATH = Path(self.temp.name) / "health.db"
        from services import system_settings
        system_settings.invalidate_cache()
        from main import app
        self.app = app

    def tearDown(self):
        for key in ("HEALTH_VAULT_HOME", "HEALTH_DB_PATH", "HEALTH_APP_PASSWORD", "HEALTH_DISABLE_AGENT_RUNTIME", "HEALTH_HOST"):
            os.environ.pop(key, None)
        self.temp.cleanup()

    def test_password_change_rotates_sessions_and_layers_over_env(self):
        with TestClient(self.app) as client:
            login = client.post("/api/auth/login", json={"password": "test-family-password"})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(client.get("/api/meta").status_code, 200)

            change = client.post("/api/settings/password", json={
                "current_password": "test-family-password",
                "new_password": "a",
            })
            self.assertEqual(change.status_code, 200)
            self.assertIsNotNone(change.json().get("warning"))  # env var still set, so file password not yet active

            # Session key was rotated: the cookie issued before the change is now invalid,
            # even though the env var still controls the active password.
            self.assertEqual(client.get("/api/meta").status_code, 401)
            self.assertEqual(client.post("/api/auth/login", json={"password": "test-family-password"}).status_code, 200)

            # Once the env var is out of the picture, the file-based password takes over.
            os.environ.pop("HEALTH_APP_PASSWORD")
            client.post("/api/auth/logout")
            self.assertEqual(client.post("/api/auth/login", json={"password": "test-family-password"}).status_code, 401)
            self.assertEqual(client.post("/api/auth/login", json={"password": "a"}).status_code, 200)

    def test_mineru_status_returns_only_safe_token_state(self):
        version = subprocess.CompletedProcess(["mineru-open-api", "version"], 0, stdout="mineru-open-api version v0.5.3\n")
        auth_show = subprocess.CompletedProcess(["mineru-open-api", "auth", "--show"], 0, stdout="Token source: config\nToken: private-value\n")
        with TestClient(self.app) as client:
            self.assertEqual(client.post("/api/auth/login", json={"password": "test-family-password"}).status_code, 200)
            with patch("services.mineru.command_path", return_value="/test/mineru-open-api"), patch("services.mineru._managed_token", return_value=None), patch("services.mineru.subprocess.run", side_effect=[version, auth_show]):
                response = client.get("/api/settings/mineru")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"installed": True, "version": "v0.5.3", "token_configured": True, "token_source": "mineru_cli", "secure_storage_available": True, "mode": "flash"})
        self.assertNotIn("private-value", response.text)

    def test_mineru_token_can_be_saved_from_any_session_and_never_returned(self):
        token = "token-that-must-never-appear-in-a-response"
        safe_status = {"installed": True, "version": "v0.5.3", "token_configured": True, "token_source": "health_vault", "secure_storage_available": True, "mode": "flash"}
        with TestClient(self.app) as client:
            self.assertEqual(client.post("/api/auth/login", json={"password": "test-family-password"}).status_code, 200)
            with patch("routers.settings.mineru.save_managed_token") as save_token, patch("routers.settings.mineru.verify_managed_token", return_value=True), patch("routers.settings.mineru.status", return_value=safe_status):
                response = client.post("/api/settings/mineru/token", json={"token": token})
        self.assertEqual(response.status_code, 200)
        save_token.assert_called_once_with(token)
        self.assertEqual(response.json(), safe_status)
        self.assertNotIn(token, response.text)

    def test_mineru_token_endpoints_require_login(self):
        with TestClient(self.app) as client:
            self.assertEqual(client.post("/api/settings/mineru/token", json={"token": "a" * 16}).status_code, 401)
            self.assertEqual(client.delete("/api/settings/mineru/token").status_code, 401)

    def test_resolved_host_prefers_env_over_file(self):
        from services import system_settings
        system_settings.save_settings({"host": "0.0.0.0"})
        self.assertEqual(system_settings.resolved_host(), "0.0.0.0")
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

    def test_remote_access_requires_an_active_tailscale_ip(self):
        from services import system_settings
        with TestClient(self.app) as client:
            self.assertEqual(client.post("/api/auth/login", json={"password": "test-family-password"}).status_code, 200)
            with patch("services.system_settings.tailscale_bind_host", return_value="100.90.80.70"):
                enabled = client.post("/api/settings/host", json={"enable_remote": True})
            self.assertEqual(enabled.status_code, 200)
            self.assertEqual(enabled.json()["host"], "100.90.80.70")
            self.assertEqual(system_settings.load_settings()["host"], "100.90.80.70")
            with patch("services.system_settings.tailscale_bind_host", return_value=None):
                refused = client.post("/api/settings/host", json={"enable_remote": True})
            self.assertEqual(refused.status_code, 409)

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

    def test_bind_warning_surfaced_in_system_settings(self):
        with TestClient(self.app) as client:
            self.assertEqual(client.post("/api/auth/login", json={"password": "test-family-password"}).status_code, 200)
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
            self.assertEqual(client.post("/api/auth/login", json={"password": "test-family-password"}).status_code, 200)
            with patch("lifecycle.request_restart", return_value=4242) as request_restart:
                response = client.post("/api/settings/restart")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)
        self.assertEqual(response.json()["pid"], 4242)
        self.assertEqual(response.json()["pending_host"], "127.0.0.1")
        request_restart.assert_called_once_with()

    def test_restart_endpoint_requires_login(self):
        with TestClient(self.app) as client:
            self.assertEqual(client.post("/api/settings/restart").status_code, 401)

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
