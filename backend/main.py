import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import agent_runtime
from auth import authenticated, password_is_configured
from database import DB_PATH, database_needs_migration, is_mock_mode, init_db
from services.backups import create_database_backup
from mock_data import seed_mock_data
from routers import activity, agent, attachments, auth, backups, imports, labs, meds, members, reminders, settings, visits, weight

app = FastAPI(title="家庭健康档案 API", version="2.0.0")
FRONTEND_DIR = os.path.abspath(os.getenv("HEALTH_FRONTEND_DIR", os.path.join(os.path.dirname(__file__), "..", "frontend")))
PUBLIC_AUTH_PATHS = {"/login", "/api/auth/login", "/api/auth/status"}


@app.middleware("http")
async def require_app_login(request: Request, call_next):
    if request.url.path not in PUBLIC_AUTH_PATHS and not authenticated(request) and not agent_runtime.is_agent_request(request):
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/login", status_code=303)
        return JSONResponse({"detail": "需要登录"}, status_code=401)
    if request.url.path not in PUBLIC_AUTH_PATHS and not password_is_configured() and not agent_runtime.is_agent_request(request):
        return JSONResponse({"detail": "服务尚未配置 HEALTH_APP_PASSWORD"}, status_code=503)
    return await call_next(request)


@app.on_event("startup")
def startup() -> None:
    if database_needs_migration():
        create_database_backup(prefix="health_preupgrade")
    init_db()
    if is_mock_mode():
        seed_mock_data()
    if os.getenv("HEALTH_DISABLE_AGENT_RUNTIME", "").lower() not in {"1", "true", "yes"}:
        port = int(os.getenv("HEALTH_PORT", "8000"))
        agent_runtime.start_agent_runtime(port)


@app.on_event("shutdown")
def shutdown() -> None:
    agent_runtime.stop_agent_runtime()


app.include_router(auth.router, prefix="/api")
app.include_router(activity.router, prefix="/api")
app.include_router(members.router, prefix="/api")
app.include_router(visits.router, prefix="/api")
app.include_router(labs.router, prefix="/api")
app.include_router(meds.router, prefix="/api")
app.include_router(weight.router, prefix="/api")
app.include_router(reminders.router, prefix="/api")
app.include_router(attachments.router, prefix="/api")
app.include_router(backups.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(settings.router, prefix="/api")


@app.get("/api/meta")
def app_meta() -> dict:
    return {"mock_mode": is_mock_mode(), "db_path": str(DB_PATH)}


@app.get("/api/agent-runtime/agent/stream")
def agent_stream(request: Request):
    return agent_runtime.proxy_agent_stream(request)


@app.api_route("/api/agent-runtime/{path:path}", methods=["GET", "POST"])
async def agent_proxy(path: str, request: Request):
    return await agent_runtime.proxy_agent_request(path, request)


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
