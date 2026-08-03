import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import DB_PATH, is_mock_mode, init_db
from mock_data import seed_mock_data
from routers import activity, agent, attachments, backups, imports, labs, meds, members, reminders, visits, weight


app = FastAPI(title="家庭健康档案 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.abspath(os.getenv("HEALTH_FRONTEND_DIR", os.path.join(os.path.dirname(__file__), "..", "frontend")))
PUBLIC_DIR = os.path.abspath(os.getenv("HEALTH_PUBLIC_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "public")))


@app.on_event("startup")
def startup() -> None:
    init_db()
    if is_mock_mode():
        seed_mock_data()


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


@app.get("/api/meta")
def app_meta() -> dict:
    return {
        "mock_mode": is_mock_mode(),
        "db_path": str(DB_PATH),
    }


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
