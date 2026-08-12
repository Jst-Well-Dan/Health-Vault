"""Safe MinerU OpenAPI CLI discovery, credential storage, and status checks."""

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import database

try:
    import keyring
    from keyring.errors import KeyringError
except ImportError:  # pragma: no cover - requirements enforce this in supported installs
    keyring = None

    class KeyringError(Exception):
        pass


_KEYRING_SERVICE = "HealthVault MinerU"
_VALID_MODES = {"flash", "extract"}


class SecureStorageError(RuntimeError):
    """The supported OS credential store cannot be read or written."""


def _keyring_account() -> str:
    root = str(database.BASE_DIR.resolve()).encode("utf-8")
    return hashlib.sha256(root).hexdigest()


def command_path() -> str | None:
    configured = os.getenv("HEALTH_MINERU_OPEN_API_CLI", "").strip()
    if configured:
        return configured if shutil.which(configured) or Path(configured).is_file() else None
    if command := shutil.which("mineru-open-api"):
        return command
    # npm does not necessarily add an active Python environment's Scripts/bin
    # directory to PATH.
    venv_command = Path(sys.executable).with_name("mineru-open-api.exe" if os.name == "nt" else "mineru-open-api")
    return str(venv_command) if venv_command.is_file() else None


def _managed_token() -> str | None:
    if keyring is None:
        raise SecureStorageError("当前环境不可用受支持的系统凭据库")
    try:
        return keyring.get_password(_KEYRING_SERVICE, _keyring_account())
    except KeyringError as exc:
        raise SecureStorageError("当前环境不可用受支持的系统凭据库") from exc


def secure_storage_available() -> bool:
    try:
        _managed_token()
    except SecureStorageError:
        return False
    return True


def save_managed_token(token: str) -> None:
    if keyring is None:
        raise SecureStorageError("当前环境不可用受支持的系统凭据库")
    try:
        keyring.set_password(_KEYRING_SERVICE, _keyring_account(), token)
    except KeyringError as exc:
        raise SecureStorageError("无法写入系统凭据库") from exc


def delete_managed_token() -> None:
    if keyring is None:
        raise SecureStorageError("当前环境不可用受支持的系统凭据库")
    try:
        keyring.delete_password(_KEYRING_SERVICE, _keyring_account())
    except keyring.errors.PasswordDeleteError:
        return
    except KeyringError as exc:
        raise SecureStorageError("无法访问系统凭据库") from exc


def resolved_mode() -> str:
    configured = os.getenv("HEALTH_MINERU_MODE", "").strip().lower()
    if configured:
        return configured
    from services import system_settings
    return str(system_settings.load_settings().get("mineru_mode") or "flash").lower()


def save_mode(mode: str) -> None:
    if mode not in _VALID_MODES:
        raise ValueError("模式只能为 flash 或 extract")
    from services import system_settings
    system_settings.save_settings({"mineru_mode": mode})


def extraction_env() -> dict[str, str]:
    """Pass an application-managed token only to the MinerU child process."""
    env = os.environ.copy()
    token = _managed_token()
    if token:
        env["MINERU_TOKEN"] = token
    return env


def verify_managed_token() -> bool:
    command = command_path()
    if not command:
        return False
    try:
        result = subprocess.run(
            [command, "auth", "--verify"], capture_output=True, text=True,
            timeout=10, check=False, env=extraction_env(),
        )
    except (OSError, subprocess.TimeoutExpired, SecureStorageError):
        return False
    return result.returncode == 0


def status() -> dict[str, str | bool | None]:
    """Return non-sensitive CLI and credential status; never return a token."""
    command = command_path()
    mode = resolved_mode()
    try:
        managed_token = _managed_token()
        storage_available = True
    except SecureStorageError:
        managed_token = None
        storage_available = False
    base = {
        "installed": bool(command),
        "version": None,
        "token_configured": bool(managed_token),
        "token_source": "health_vault" if managed_token else None,
        "secure_storage_available": storage_available,
        "mode": mode,
    }
    if not command:
        return base

    try:
        version_result = subprocess.run([command, "version"], capture_output=True, text=True, timeout=5, check=False)
        version_match = re.search(r"\bv?\d+(?:\.\d+)+\b", version_result.stdout)
        base["version"] = version_match.group(0) if version_result.returncode == 0 and version_match else None
        if not managed_token:
            auth_result = subprocess.run([command, "auth", "--show"], capture_output=True, text=True, timeout=5, check=False)
            if auth_result.returncode == 0 and "Token source:" in auth_result.stdout:
                base["token_configured"] = True
                base["token_source"] = "mineru_cli"
    except (OSError, subprocess.TimeoutExpired):
        base["installed"] = False
        base["version"] = None
    return base
