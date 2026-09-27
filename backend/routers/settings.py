import os
import platform

from fastapi import APIRouter, HTTPException, Request
from typing import Literal

from pydantic import BaseModel, Field

from services import mineru, system_settings

router = APIRouter(tags=["settings"])


def _current_bound_host() -> str:
    # HEALTH_BOUND_HOST is set by run_backend.py to the address actually passed to
    # uvicorn.run() this process, which may differ from HEALTH_HOST (unset) or from
    # settings.json (changed after startup, takes effect only on restart).
    return os.getenv("HEALTH_BOUND_HOST") or os.getenv("HEALTH_HOST", "127.0.0.1")


def _bind_warning() -> str | None:
    # Set by run_backend.py at startup (stale/absent Tailscale IP handling).
    warning = os.getenv("HEALTH_BOUND_WARNING")
    return warning or None


class HostUpdate(BaseModel):
    enable_remote: bool


class AutostartUpdate(BaseModel):
    enabled: bool


class MineruModeUpdate(BaseModel):
    mode: Literal["flash", "extract"]


class MineruTokenUpdate(BaseModel):
    token: str = Field(min_length=16, max_length=4096)


@router.get("/settings/system")
def get_system_settings() -> dict:
    current_host = _current_bound_host()
    pending_host = system_settings.resolved_host()
    return {
        "platform": platform.system(),
        "current_host": current_host,
        "pending_host": pending_host,
        "restart_required": current_host != pending_host,
        "bind_warning": _bind_warning(),
        "autostart_supported": system_settings.autostart_supported(),
        "autostart_enabled": system_settings.autostart_status() if system_settings.autostart_supported() else False,
        "tailscale": system_settings.detect_tailscale(),
    }


@router.get("/settings/mineru")
def get_mineru_settings() -> dict:
    return mineru.status()


@router.put("/settings/mineru/mode")
def update_mineru_mode(payload: MineruModeUpdate) -> dict:
    mineru.save_mode(payload.mode)
    return mineru.status()


@router.post("/settings/mineru/token")
def save_mineru_token(payload: MineruTokenUpdate) -> dict:
    token = payload.token.strip()
    if not token:
        raise HTTPException(status_code=422, detail="Token 不能为空")
    try:
        mineru.save_managed_token(token)
        if not mineru.verify_managed_token():
            mineru.delete_managed_token()
            raise HTTPException(status_code=422, detail="MinerU Token 格式验证失败，请检查后重试")
    except mineru.SecureStorageError as exc:
        raise HTTPException(status_code=503, detail="无法访问系统凭据库，未保存 Token") from exc
    return mineru.status()


@router.delete("/settings/mineru/token")
def delete_mineru_token() -> dict:
    try:
        mineru.delete_managed_token()
    except mineru.SecureStorageError as exc:
        raise HTTPException(status_code=503, detail="无法访问系统凭据库") from exc
    return mineru.status()


@router.post("/settings/host")
def update_host(payload: HostUpdate) -> dict:
    # Tailscale-only：只绑定检测到的 100.x，不接受 0.0.0.0/局域网手填。
    if payload.enable_remote:
        current = system_settings.tailscale_bind_host()
        if not current:
            raise HTTPException(status_code=409, detail="Tailscale 未连接，先连接后再启用")
        system_settings.save_settings({"host": current})
        return {"ok": True, "host": current, "restart_required": _current_bound_host() != current}
    new_host = "127.0.0.1"
    system_settings.save_settings({"host": new_host})
    return {"ok": True, "host": new_host, "restart_required": _current_bound_host() != new_host}


@router.post("/settings/restart")
def restart_app() -> dict:
    """Browser-triggered self-restart: spawn a replacement process that re-binds
    per current settings, then stop this server gracefully (~2s)."""
    import lifecycle

    pid = lifecycle.request_restart()
    return {"ok": True, "pid": pid, "pending_host": system_settings.resolved_host()}


@router.post("/settings/autostart")
def update_autostart(payload: AutostartUpdate) -> dict:
    if not system_settings.autostart_supported():
        raise HTTPException(status_code=400, detail="当前平台暂不支持一键开机自启，请参考 README 手动配置")
    result = system_settings.enable_autostart() if payload.enabled else system_settings.disable_autostart()
    return result
