from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import COOKIE_NAME, SESSION_TTL_SECONDS, authenticated, issue_session, login_allowed, password_is_configured, verify_password

router = APIRouter(tags=["auth"])


class LoginPayload(BaseModel):
    password: str


@router.get("/auth/status")
def auth_status(request: Request) -> dict:
    return {"authenticated": authenticated(request), "password_configured": password_is_configured()}


@router.post("/auth/login")
def login(payload: LoginPayload, request: Request) -> JSONResponse:
    host = request.client.host if request.client else "unknown"
    if not password_is_configured():
        raise HTTPException(status_code=503, detail="服务尚未配置 HEALTH_APP_PASSWORD")
    if not login_allowed(host):
        raise HTTPException(status_code=429, detail="登录尝试过多，请 15 分钟后再试")
    if not verify_password(payload.password, host):
        raise HTTPException(status_code=401, detail="密码错误")
    response = JSONResponse({"ok": True})
    response.set_cookie(COOKIE_NAME, issue_session(), max_age=SESSION_TTL_SECONDS, httponly=True, samesite="strict", secure=False, path="/")
    return response


@router.post("/auth/logout")
def logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
