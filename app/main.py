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

from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import HttpUrl
from fastapi_mcp import FastApiMCP, AuthConfig, OAuthMetadata

from app.config import settings
from app.db import engine, Base
from app.dependencies import get_current_mcp_user
from app.routes import auth, dashboard, monitors, versions, settings as settings_routes, worker_tick, pages, oauth, api
from app.services.scheduler_service import scheduler_loop

# Keep schema bootstrap out of production/serverless imports. Run
# `python -m scripts.init_db` against a new database before first deploy.
if not settings.is_vercel and not settings.is_production:
    Base.metadata.create_all(bind=engine)

# Background scheduler task handle
_scheduler_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate production configuration before touching the database or artifact store.
    if settings.is_production:
        settings.validate_production_config()

    # Opt-in only: use this to recover a fresh database when the external migration
    # workflow is unavailable. Keep the flag off normally; the runner serializes
    # competing cold starts and refuses an existing unversioned schema.
    if settings.MIGRATE_DATABASE_ON_STARTUP:
        from app.database_migrations import apply_database_migrations
        apply_database_migrations(require_postgres=True)

    # Vercel's function filesystem is not durable; S3-compatible object storage
    # is used there. Local/Docker development uses the mounted artifact directory.
    if not settings.is_vercel:
        settings.artifact_dir_path.mkdir(parents=True, exist_ok=True)

    # A perpetual scheduler belongs in its own process in production and on Vercel.
    global _scheduler_task
    if (
        settings.APP_ENV != "test"
        and settings.ENABLE_INLINE_SCHEDULER
        and not settings.is_vercel
        and not settings.is_production
    ):
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
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# Mount static assets
static_path = Path(__file__).parent / "static"
# Vercel's deployed bundle is read-only. The CSS build step creates dist/app.css.
if not settings.is_vercel:
    static_path.mkdir(parents=True, exist_ok=True)
    (static_path / "dist").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

@app.get("/healthz", include_in_schema=False)
def healthz():
    """Lightweight process health probe; external dependencies are configured separately."""
    return {"status": "ok", "service": "changewatch"}


# Include Routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(monitors.router)
app.include_router(versions.router)
app.include_router(settings_routes.router)
app.include_router(worker_tick.router)
app.include_router(pages.router)
app.include_router(oauth.router)
app.include_router(api.router)

# Model Context Protocol (MCP) Server setup with native OAuth 2.0
_base_url_str = (
    "https://changewatch.aayushsrivastava.com"
    if (settings.is_production or (settings.APP_BASE_URL and "changewatch.aayushsrivastava.com" in settings.APP_BASE_URL))
    else (
        settings.APP_BASE_URL.rstrip("/")
        if settings.APP_BASE_URL and settings.APP_BASE_URL.startswith("http")
        else "http://localhost:8000"
    )
)

mcp_auth_config = AuthConfig(
    dependencies=[Depends(get_current_mcp_user)],
    custom_oauth_metadata=OAuthMetadata(
        issuer=HttpUrl(_base_url_str),
        authorization_endpoint=HttpUrl(f"{_base_url_str}/oauth/authorize"),
        token_endpoint=HttpUrl(f"{_base_url_str}/oauth/token"),
        registration_endpoint=HttpUrl(f"{_base_url_str}/oauth/register"),
        scopes_supported=["openid", "profile", "email", "monitors"],
        response_types_supported=["code"],
        grant_types_supported=["authorization_code"],
        token_endpoint_auth_methods_supported=["none", "client_secret_post"],
        code_challenge_methods_supported=["S256", "plain"],
    ),
)

mcp = FastApiMCP(
    app,
    name="ChangeWatch MCP Server",
    description="Full management suite for web monitors, checks, and diffs linked to your ChangeWatch account.",
    include_tags=["mcp"],
    auth_config=mcp_auth_config,
)
mcp.mount_http(app, "/mcp")
mcp.mount_sse(app, "/sse")

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
