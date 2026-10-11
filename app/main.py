import sys
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

# On Windows, ensure default event loop policy supports subprocesses
if sys.platform == "win32":
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.db import engine, Base
from app.routes import auth, dashboard, monitors, versions, settings as settings_routes
from app.services.scheduler_service import scheduler_loop

# Initialize database tables
Base.metadata.create_all(bind=engine)

# Background scheduler task handle
_scheduler_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure artifact directory exists
    settings.artifact_dir_path.mkdir(parents=True, exist_ok=True)

    # Start background scheduler loop in development mode
    global _scheduler_task
    if settings.APP_ENV != "test":
        _scheduler_task = asyncio.create_task(scheduler_loop(interval_seconds=30))

    yield

    # Clean shutdown of scheduler
    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="ChangeWatch",
    description="Public web page monitoring service with noise filtering and visual diffs",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static assets
static_path = Path(__file__).parent / "static"
static_path.mkdir(parents=True, exist_ok=True)
(static_path / "dist").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Include Routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(monitors.router)
app.include_router(versions.router)
app.include_router(settings_routes.router)

templates = Jinja2Templates(directory="app/templates")


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(request, "base.html", {
        "current_user": None,
        "error": "The requested resource was not found.",
    }, status_code=404)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return templates.TemplateResponse(request, "base.html", {
        "current_user": None,
        "error": "An unexpected server error occurred. Please try again.",
    }, status_code=500)
