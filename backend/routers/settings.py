import os
import platform

from fastapi import APIRouter, HTTPException, Request
from typing import Literal

from pydantic import BaseModel, Field

from services import mineru, system_settings

router = APIRouter(tags=["settings"])


def _current_bound_hosts() -> list[str]:
    # HEALTH_BOUND_HOSTS is set by run_backend.py to the addresses actually bound
    # this run (dual-listen: loopback + Tailscale). It may differ from HEALTH_HOST
    # (unset) or from settings.json (changed after startup, takes effect on restart).
    raw = os.getenv("HEALTH_BOUND_HOSTS")
    if raw:
        hosts = [h.strip() for h in raw.split(",") if h.strip()]
        if hosts:
            return hosts
    legacy = os.getenv("HEALTH_BOUND_HOST") or os.getenv("HEALTH_HOST", "127.0.0.1")
    return [legacy]


def _primary_host(hosts: list[str]) -> str:
    """Legacy single-host view: the remote address when present, else loopback."""
    for host in reversed(hosts):
        if not system_settings.is_loopback_host(host):
            return host
    return hosts[0] if hosts else "127.0.0.1"


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
    current_hosts = _current_bound_hosts()
    pending_hosts = system_settings.resolved_pending_hosts()
    return {
        "platform": platform.system(),
        "current_hosts": current_hosts,
        "pending_hosts": pending_hosts,
        "current_host": _primary_host(current_hosts),
        "pending_host": _primary_host(pending_hosts),
        "restart_required": set(current_hosts) != set(pending_hosts),
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
        pending_hosts = system_settings.resolved_pending_hosts()
        return {"ok": True, "host": current, "pending_hosts": pending_hosts, "restart_required": set(_current_bound_hosts()) != set(pending_hosts)}
    new_host = "127.0.0.1"
    system_settings.save_settings({"host": new_host})
    pending_hosts = system_settings.resolved_pending_hosts()
    return {"ok": True, "host": new_host, "pending_hosts": pending_hosts, "restart_required": set(_current_bound_hosts()) != set(pending_hosts)}


@router.post("/settings/restart")
def restart_app() -> dict:
    """Browser-triggered self-restart: spawn a replacement process that re-binds
    per current settings, then stop this server gracefully (~2s)."""
    import lifecycle

    pid = lifecycle.request_restart()
    pending_hosts = system_settings.resolved_pending_hosts()
    return {"ok": True, "pid": pid, "pending_hosts": pending_hosts, "pending_host": _primary_host(pending_hosts)}


@router.post("/settings/autostart")
def update_autostart(payload: AutostartUpdate) -> dict:
    if not system_settings.autostart_supported():
        raise HTTPException(status_code=400, detail="当前平台暂不支持一键开机自启，请参考 README 手动配置")
    result = system_settings.enable_autostart() if payload.enabled else system_settings.disable_autostart()
    return result
