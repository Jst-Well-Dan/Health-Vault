import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import DB_PATH, database_needs_migration, is_mock_mode, init_db
from services.backups import create_database_backup, prune_old_snapshots
from mock_data import seed_mock_data
from routers import activity, attachments, backups, labs, meds, members, pet_care, search, settings, visits, weight

app = FastAPI(title="家庭健康档案 API", version="2.0.0")
FRONTEND_DIR = os.path.abspath(os.getenv("HEALTH_FRONTEND_DIR", os.path.join(os.path.dirname(__file__), "..", "frontend")))


@app.on_event("startup")
def startup() -> None:
    if database_needs_migration():
        create_database_backup(prefix="health_preupgrade")
    try:
        prune_old_snapshots()
    except Exception:
        pass
    init_db()
    if is_mock_mode():
        seed_mock_data()


app.include_router(activity.router, prefix="/api")
app.include_router(members.router, prefix="/api")
app.include_router(visits.router, prefix="/api")
app.include_router(labs.router, prefix="/api")
app.include_router(meds.router, prefix="/api")
app.include_router(weight.router, prefix="/api")
app.include_router(pet_care.router, prefix="/api")
app.include_router(attachments.router, prefix="/api")
app.include_router(backups.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(search.router, prefix="/api")


@app.get("/api/meta")
def app_meta() -> dict:
    return {"mock_mode": is_mock_mode(), "db_path": str(DB_PATH)}


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
