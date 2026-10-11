from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Request, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import get_db
from app.models.user import User
from app.models.monitor import Monitor
from app.dependencies import get_current_user_optional, get_current_user, get_or_create_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    return templates.TemplateResponse(request, "landing.html", {
        "current_user": user,
    })


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Monitor).filter(Monitor.user_id == current_user.id, Monitor.state != "deleted")
    all_monitors = query.order_by(Monitor.created_at.desc()).all()

    # Aggregate counts
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    counts = {
        "ok": sum(1 for m in all_monitors if m.last_status == "ok" and m.state == "active"),
        "active": sum(1 for m in all_monitors if m.state == "active"),
        "paused": sum(1 for m in all_monitors if m.state == "paused"),
        "attention": sum(1 for m in all_monitors if m.last_status in ("error", "blocked")),
        "errors": sum(1 for m in all_monitors if m.last_status in ("error", "blocked")),
        "recent_changes": sum(1 for m in all_monitors if m.last_changed_at and m.last_changed_at >= day_ago),
    }

    # Filter monitors if requested
    filtered_monitors = all_monitors
    if filter == "active":
        filtered_monitors = [m for m in all_monitors if m.state == "active"]
    elif filter == "paused":
        filtered_monitors = [m for m in all_monitors if m.state == "paused"]
    elif filter == "errors":
        filtered_monitors = [m for m in all_monitors if m.last_status in ("error", "blocked")]

    csrf_token = get_or_create_csrf_token(request)

    return templates.TemplateResponse(request, "dashboard.html", {
        "current_user": current_user,
        "csrf_token": csrf_token,
        "monitors": filtered_monitors,
        "counts": counts,
        "active_filter": filter,
    })
