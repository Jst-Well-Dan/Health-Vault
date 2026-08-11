"""Persisted local settings for remote access: listen host, password hash, autostart."""

import hashlib
import hmac
import json
import os
import platform
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any

import database

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WINDOWS_SCRIPTS_DIR = _PROJECT_ROOT / "scripts" / "windows"
_MACOS_SCRIPTS_DIR = _PROJECT_ROOT / "scripts" / "macos"
_TASK_NAME = "HealthVaultWeb"
_LAUNCHD_LABEL = "com.healthvault.web"
_PBKDF2_ITERATIONS = 200_000

# In-memory cache: password_is_configured() runs on every request via the auth
# middleware, so load_settings() must not hit disk each time. Invalidated on
# save_settings() and (for tests that swap database.BASE_DIR) invalidate_cache().
_cache: dict[str, Any] | None = None


def _settings_path() -> Path:
    return database.BASE_DIR / "data" / "settings.json"


def invalidate_cache() -> None:
    global _cache
    _cache = None


def load_settings() -> dict[str, Any]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_settings_path().read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {}
    return _cache


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    global _cache
    merged = {**load_settings(), **patch}
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    _cache = merged
    return merged


def resolved_host() -> str:
    return os.getenv("HEALTH_HOST") or load_settings().get("host") or "127.0.0.1"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password_hash(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(actual, expected)


def _tailscale_binary() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    system = platform.system()
    if system == "Windows":
        candidate = Path(r"C:\Program Files\Tailscale\tailscale.exe")
        if candidate.exists():
            return str(candidate)
    elif system == "Darwin":
        candidate = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
        if candidate.exists():
            return str(candidate)
    return None


def detect_tailscale() -> dict[str, Any]:
    binary = _tailscale_binary()
    if not binary:
        return {"installed": False, "connected": False, "ip": None}
    try:
        result = subprocess.run([binary, "ip", "-4"], timeout=3, capture_output=True, text=True)
    except (OSError, subprocess.TimeoutExpired):
        return {"installed": True, "connected": False, "ip": None}
    ip = result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else None
    if result.returncode == 0 and ip and ip.startswith("100."):
        return {"installed": True, "connected": True, "ip": ip}
    return {"installed": True, "connected": False, "ip": None}


def tailscale_bind_host() -> str | None:
    """Return the active Tailscale IPv4 address, never a wildcard bind address."""
    info = detect_tailscale()
    return str(info["ip"]) if info["connected"] and info["ip"] else None


def autostart_supported() -> bool:
    return platform.system() in {"Windows", "Darwin"}


def autostart_status() -> bool:
    system = platform.system()
    try:
        if system == "Windows":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-ScheduledTask -TaskName '{_TASK_NAME}' -ErrorAction SilentlyContinue"],
                timeout=15, capture_output=True, text=True,
            )
            return bool(result.stdout.strip())
        if system == "Darwin":
            result = subprocess.run(
                ["launchctl", "list", _LAUNCHD_LABEL], timeout=10, capture_output=True, text=True,
            )
            return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    return False


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _run_windows_elevated(script: Path, *args: str) -> dict[str, Any]:
    ps_args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    array_literal = "@(" + ",".join(_ps_quote(a) for a in ps_args) + ")"
    command = f"Start-Process powershell -Verb RunAs -Wait -ArgumentList {array_literal}"
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            timeout=60, capture_output=True, text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "message": str(exc)}
    if result.returncode != 0:
        return {"ok": False, "message": (result.stderr or "").strip() or "PowerShell 提权执行失败"}
    return {"ok": True, "message": ""}


def _run_script(script: Path, *args: str, timeout: int = 30) -> dict[str, Any]:
    try:
        if script.suffix == ".ps1":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
                timeout=timeout, capture_output=True, text=True,
            )
        else:
            result = subprocess.run(["bash", str(script), *args], timeout=timeout, capture_output=True, text=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "message": str(exc)}
    if result.returncode != 0:
        return {"ok": False, "message": (result.stderr or "").strip() or "脚本执行失败"}
    return {"ok": True, "message": (result.stdout or "").strip()}


def enable_autostart() -> dict[str, Any]:
    system = platform.system()
    if system == "Windows":
        return _run_script(_WINDOWS_SCRIPTS_DIR / "setup-autostart.ps1", "-ProjectPath", str(_PROJECT_ROOT))
    if system == "Darwin":
        return _run_script(_MACOS_SCRIPTS_DIR / "setup-autostart.sh", str(_PROJECT_ROOT))
    return {"ok": False, "message": "当前平台暂不支持一键开机自启，请参考 README 手动配置"}


def disable_autostart() -> dict[str, Any]:
    system = platform.system()
    if system == "Windows":
        return _run_script(_WINDOWS_SCRIPTS_DIR / "remove-autostart.ps1")
    if system == "Darwin":
        return _run_script(_MACOS_SCRIPTS_DIR / "remove-autostart.sh")
    return {"ok": False, "message": "当前平台暂不支持一键开机自启，请参考 README 手动配置"}
