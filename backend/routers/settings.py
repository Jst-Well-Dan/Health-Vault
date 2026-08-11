import os
import platform

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import auth
from services import system_settings

router = APIRouter(tags=["settings"])


def _current_bound_host() -> str:
    # HEALTH_BOUND_HOST is set by run_backend.py to the address actually passed to
    # uvicorn.run() this process, which may differ from HEALTH_HOST (unset) or from
    # settings.json (changed after startup, takes effect only on restart).
    return os.getenv("HEALTH_BOUND_HOST") or os.getenv("HEALTH_HOST", "127.0.0.1")


class HostUpdate(BaseModel):
    enable_remote: bool


class PasswordUpdate(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class AutostartUpdate(BaseModel):
    enabled: bool


@router.get("/settings/system")
def get_system_settings() -> dict:
    current_host = _current_bound_host()
    pending_host = system_settings.resolved_host()
    if os.getenv("HEALTH_APP_PASSWORD"):
        password_source = "env"
    elif system_settings.load_settings().get("password_hash"):
        password_source = "file"
    else:
        password_source = "unset"
    return {
        "platform": platform.system(),
        "current_host": current_host,
        "pending_host": pending_host,
        "restart_required": current_host != pending_host,
        "password_source": password_source,
        "autostart_supported": system_settings.autostart_supported(),
        "autostart_enabled": system_settings.autostart_status() if system_settings.autostart_supported() else False,
        "tailscale": system_settings.detect_tailscale(),
    }


@router.post("/settings/host")
def update_host(payload: HostUpdate) -> dict:
    new_host = "127.0.0.1"
    if payload.enable_remote:
        new_host = system_settings.tailscale_bind_host()
        if not new_host:
            raise HTTPException(status_code=409, detail="未检测到已连接的 Tailscale IPv4 地址，不能启用手机访问")
    system_settings.save_settings({"host": new_host})
    return {"ok": True, "host": new_host, "restart_required": _current_bound_host() != new_host}


@router.post("/settings/password")
def update_password(payload: PasswordUpdate, request: Request) -> dict:
    host = request.client.host if request.client else "unknown"
    if not auth.login_allowed(host):
        raise HTTPException(status_code=429, detail="尝试过多，请稍后再试")
    if not auth.verify_password(payload.current_password, host):
        raise HTTPException(status_code=401, detail="当前密码错误")
    system_settings.save_settings({"password_hash": system_settings.hash_password(payload.new_password)})
    auth.rotate_session_key()

    warning = None
    if os.getenv("HEALTH_APP_PASSWORD"):
        warning = "当前仍由环境变量 HEALTH_APP_PASSWORD 控制登录密码，网页修改不会生效，请同时更新或取消该环境变量。"
    return {"ok": True, "warning": warning}


@router.post("/settings/autostart")
def update_autostart(payload: AutostartUpdate) -> dict:
    if not system_settings.autostart_supported():
        raise HTTPException(status_code=400, detail="当前平台暂不支持一键开机自启，请参考 README 手动配置")
    result = system_settings.enable_autostart() if payload.enabled else system_settings.disable_autostart()
    return result
