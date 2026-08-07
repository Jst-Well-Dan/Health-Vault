"""Shared-password web authentication for the single-family deployment."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import HTTPException, Request

COOKIE_NAME = "health_vault_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 10 * 60
LOCKOUT_SECONDS = 15 * 60
_attempts: dict[str, deque[float]] = defaultdict(deque)
_locked_until: dict[str, float] = {}


def _data_home() -> Path:
    return Path(os.getenv("HEALTH_VAULT_HOME", Path(__file__).resolve().parent.parent)).resolve() / "data"


def _key_path() -> Path:
    return _data_home() / "session-key.bin"


def _session_key() -> bytes:
    configured = os.getenv("HEALTH_SESSION_SECRET")
    if configured:
        return hashlib.sha256(configured.encode("utf-8")).digest()
    path = _key_path()
    try:
        key = path.read_bytes()
        if len(key) == 32:
            return key
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def configured_password() -> str | None:
    value = os.getenv("HEALTH_APP_PASSWORD")
    return value if value else None


def password_is_configured() -> bool:
    return configured_password() is not None


def _encode(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(_session_key(), body, hashlib.sha256).digest()
    return f"{body.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _decode(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body_text, signature_text = token.split(".", 1)
    try:
        body = body_text.encode()
        expected = hmac.new(_session_key(), body, hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + b"=" * (-len(body) % 4)))
        return payload if int(payload.get("exp", 0)) >= int(time.time()) else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def authenticated(request: Request) -> bool:
    return _decode(request.cookies.get(COOKIE_NAME)) is not None


def issue_session() -> str:
    return _encode({"exp": int(time.time()) + SESSION_TTL_SECONDS, "nonce": secrets.token_urlsafe(16)})


def login_allowed(client_host: str) -> bool:
    return time.time() >= _locked_until.get(client_host, 0)


def verify_password(password: str, client_host: str) -> bool:
    now = time.time()
    attempts = _attempts[client_host]
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    expected = configured_password()
    if not expected or not hmac.compare_digest(password.encode(), expected.encode()):
        attempts.append(now)
        if len(attempts) >= MAX_LOGIN_ATTEMPTS:
            _locked_until[client_host] = now + LOCKOUT_SECONDS
            attempts.clear()
        return False
    _attempts.pop(client_host, None)
    _locked_until.pop(client_host, None)
    return True


def require_password_configured() -> None:
    if not password_is_configured():
        raise HTTPException(status_code=503, detail="服务尚未配置 HEALTH_APP_PASSWORD")
