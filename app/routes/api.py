from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, HttpUrl
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.models.monitor import Monitor
from app.models.version import Version
from app.dependencies import get_current_mcp_user
from app.services.url_safety import validate_public_url
from app.services.queue_service import enqueue_check, process_check_job
from app.services.diff_engine import generate_text_diff, generate_diff_summary
from app.config import settings

router = APIRouter(prefix="/api", tags=["mcp"])


# Pydantic Schemas for MCP Tools
class MonitorSummary(BaseModel):
    id: str
    name: str
    url: str
    state: str
    is_active: bool
    interval_minutes: int
    sensitivity: str
    last_status: str
    last_checked_at: Optional[str] = None
    last_changed_at: Optional[str] = None
    next_check_at: Optional[str] = None


class MonitorDetail(MonitorSummary):
    include_selectors: List[str]
    ignore_selectors: List[str]
    keywords: List[str]
    numeric_selector: Optional[str] = None
    total_versions: int
    last_error_message: Optional[str] = None


class CreateMonitorRequest(BaseModel):
    url: str = Field(..., description="Target web page URL to monitor (must be a valid public HTTP/HTTPS URL)")
    name: str = Field(..., description="Human-readable title or label for this monitor")
    interval_minutes: int = Field(60, ge=15, le=1440, description="Check frequency in minutes (15 to 1440)")
    sensitivity: str = Field("medium", description="Change sensitivity threshold: 'low', 'medium', or 'high'")
    include_selectors: Optional[List[str]] = Field(default=[], description="CSS selectors for regions to isolate")
    ignore_selectors: Optional[List[str]] = Field(default=[], description="CSS selectors for noise elements to strip")
    keywords: Optional[List[str]] = Field(default=[], description="Keywords to alert on if detected")
    numeric_selector: Optional[str] = Field(None, description="CSS selector targeting a numeric price or metric")


class UpdateMonitorRequest(BaseModel):
    name: Optional[str] = Field(None, description="New name for the monitor")
    interval_minutes: Optional[int] = Field(None, ge=15, le=1440, description="Check interval in minutes")
    sensitivity: Optional[str] = Field(None, description="Change sensitivity threshold ('low', 'medium', 'high')")
    include_selectors: Optional[List[str]] = Field(None, description="List of CSS selectors to isolate")
    ignore_selectors: Optional[List[str]] = Field(None, description="List of CSS selectors to ignore")
    keywords: Optional[List[str]] = Field(None, description="Keywords to match")
    numeric_selector: Optional[str] = Field(None, description="Numeric selector")


class DiffResult(BaseModel):
    monitor_id: str
    from_version_number: Optional[int] = None
    to_version_number: int
    summary: str
    diff_lines_preview: List[str]


# MCP Tool Endpoints
@router.get("/monitors", response_model=List[MonitorSummary], summary="List all monitors", operation_id="list_monitors")
async def list_monitors(
    current_user: User = Depends(get_current_mcp_user),
    db: Session = Depends(get_db),
):
    """
    List all active and paused web monitors belonging to the authenticated user.
    Returns status, check interval, and last check timestamps for each monitor.
    """
    monitors = db.query(Monitor).filter(
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted",
    ).order_by(Monitor.created_at.desc()).all()

    return [
        MonitorSummary(
            id=m.id,
            name=m.name,
            url=m.url,
            state=m.state,
            is_active=m.is_active,
            interval_minutes=m.interval_minutes,
            sensitivity=m.sensitivity,
            last_status=m.last_status,
            last_checked_at=m.last_checked_at.isoformat() if m.last_checked_at else None,
            last_changed_at=m.last_changed_at.isoformat() if m.last_changed_at else None,
            next_check_at=m.next_check_at.isoformat() if m.next_check_at else None,
        )
        for m in monitors
    ]


@router.get("/monitors/{monitor_id}", response_model=MonitorDetail, summary="Get monitor details", operation_id="get_monitor")
async def get_monitor(
    monitor_id: str,
    current_user: User = Depends(get_current_mcp_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve comprehensive details, configuration, and version counts for a single monitor.
    """
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted",
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    version_count = db.query(Version).filter(Version.monitor_id == monitor.id).count()

    return MonitorDetail(
        id=monitor.id,
        name=monitor.name,
        url=monitor.url,
        state=monitor.state,
        is_active=monitor.is_active,
        interval_minutes=monitor.interval_minutes,
        sensitivity=monitor.sensitivity,
        last_status=monitor.last_status,
        last_checked_at=monitor.last_checked_at.isoformat() if monitor.last_checked_at else None,
        last_changed_at=monitor.last_changed_at.isoformat() if monitor.last_changed_at else None,
        next_check_at=monitor.next_check_at.isoformat() if monitor.next_check_at else None,
        include_selectors=monitor.include_selectors,
        ignore_selectors=monitor.ignore_selectors,
        keywords=monitor.keywords,
        numeric_selector=monitor.numeric_selector,
        total_versions=version_count,
        last_error_message=monitor.last_error_message,
    )


@router.post("/monitors", response_model=MonitorDetail, status_code=status.HTTP_201_CREATED, summary="Create a new web monitor", operation_id="create_monitor")
async def create_monitor(
    body: CreateMonitorRequest,
    current_user: User = Depends(get_current_mcp_user),
    db: Session = Depends(get_db),
):
    """
    Create a new webpage monitor. ChangeWatch performs SSRF verification on the URL
    and enqueues an initial baseline capture automatically.
    """
    is_safe, canonical_url, err_code = validate_public_url(body.url.strip())
    if not is_safe:
        raise HTTPException(status_code=400, detail=f"Target URL is not permitted or failed safety check: {canonical_url} ({err_code})")

    monitor = Monitor(
        user_id=current_user.id,
        name=body.name.strip()[:120],
        url=canonical_url,
        interval_minutes=body.interval_minutes,
        sensitivity=body.sensitivity if body.sensitivity in ("low", "medium", "high") else "medium",
        include_selectors=body.include_selectors or [],
        ignore_selectors=body.ignore_selectors or [],
        keywords=body.keywords or [],
        numeric_selector=body.numeric_selector.strip() if body.numeric_selector else None,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    # Enqueue baseline check
    job = enqueue_check(db, monitor.id, is_manual=True)
    if job and (settings.run_inline_checks or settings.is_vercel):
        await process_check_job(db, job)

    return MonitorDetail(
        id=monitor.id,
        name=monitor.name,
        url=monitor.url,
        state=monitor.state,
        is_active=monitor.is_active,
        interval_minutes=monitor.interval_minutes,
        sensitivity=monitor.sensitivity,
        last_status=monitor.last_status,
        last_checked_at=monitor.last_checked_at.isoformat() if monitor.last_checked_at else None,
        last_changed_at=monitor.last_changed_at.isoformat() if monitor.last_changed_at else None,
        next_check_at=monitor.next_check_at.isoformat() if monitor.next_check_at else None,
        include_selectors=monitor.include_selectors,
        ignore_selectors=monitor.ignore_selectors,
        keywords=monitor.keywords,
        numeric_selector=monitor.numeric_selector,
        total_versions=0,
    )


@router.patch("/monitors/{monitor_id}", response_model=MonitorDetail, summary="Update monitor settings", operation_id="update_monitor")
async def update_monitor(
    monitor_id: str,
    body: UpdateMonitorRequest,
    current_user: User = Depends(get_current_mcp_user),
    db: Session = Depends(get_db),
):
    """
    Update configuration options (name, interval, sensitivity, selectors, keywords) for an existing monitor.
    """
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted",
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    if body.name is not None:
        monitor.name = body.name.strip()[:120]
    if body.interval_minutes is not None:
        monitor.interval_minutes = body.interval_minutes
    if body.sensitivity is not None and body.sensitivity in ("low", "medium", "high"):
        monitor.sensitivity = body.sensitivity
    if body.include_selectors is not None:
        monitor.include_selectors = body.include_selectors
    if body.ignore_selectors is not None:
        monitor.ignore_selectors = body.ignore_selectors
    if body.keywords is not None:
        monitor.keywords = body.keywords
    if body.numeric_selector is not None:
        monitor.numeric_selector = body.numeric_selector.strip() if body.numeric_selector else None

    db.commit()
    db.refresh(monitor)

    version_count = db.query(Version).filter(Version.monitor_id == monitor.id).count()

    return MonitorDetail(
        id=monitor.id,
        name=monitor.name,
        url=monitor.url,
        state=monitor.state,
        is_active=monitor.is_active,
        interval_minutes=monitor.interval_minutes,
        sensitivity=monitor.sensitivity,
        last_status=monitor.last_status,
        last_checked_at=monitor.last_checked_at.isoformat() if monitor.last_checked_at else None,
        last_changed_at=monitor.last_changed_at.isoformat() if monitor.last_changed_at else None,
        next_check_at=monitor.next_check_at.isoformat() if monitor.next_check_at else None,
        include_selectors=monitor.include_selectors,
        ignore_selectors=monitor.ignore_selectors,
        keywords=monitor.keywords,
        numeric_selector=monitor.numeric_selector,
        total_versions=version_count,
    )


@router.post("/monitors/{monitor_id}/pause", response_model=MonitorSummary, summary="Pause a monitor", operation_id="pause_monitor")
async def pause_monitor(
    monitor_id: str,
    current_user: User = Depends(get_current_mcp_user),
    db: Session = Depends(get_db),
):
    """
    Pause an active monitor so that scheduled background checks are suspended.
    """
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted",
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    monitor.is_active = False
    monitor.state = "paused"
    db.commit()
    db.refresh(monitor)

    return MonitorSummary(
        id=monitor.id,
        name=monitor.name,
        url=monitor.url,
        state=monitor.state,
        is_active=monitor.is_active,
        interval_minutes=monitor.interval_minutes,
        sensitivity=monitor.sensitivity,
        last_status=monitor.last_status,
        last_checked_at=monitor.last_checked_at.isoformat() if monitor.last_checked_at else None,
        last_changed_at=monitor.last_changed_at.isoformat() if monitor.last_changed_at else None,
        next_check_at=monitor.next_check_at.isoformat() if monitor.next_check_at else None,
    )


@router.post("/monitors/{monitor_id}/resume", response_model=MonitorSummary, summary="Resume a paused monitor", operation_id="resume_monitor")
async def resume_monitor(
    monitor_id: str,
    current_user: User = Depends(get_current_mcp_user),
    db: Session = Depends(get_db),
):
    """
    Resume a paused monitor to restart regular scheduled checks.
    """
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted",
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    monitor.is_active = True
    monitor.state = "active"
    db.commit()
    db.refresh(monitor)

    return MonitorSummary(
        id=monitor.id,
        name=monitor.name,
        url=monitor.url,
        state=monitor.state,
        is_active=monitor.is_active,
        interval_minutes=monitor.interval_minutes,
        sensitivity=monitor.sensitivity,
        last_status=monitor.last_status,
        last_checked_at=monitor.last_checked_at.isoformat() if monitor.last_checked_at else None,
        last_changed_at=monitor.last_changed_at.isoformat() if monitor.last_changed_at else None,
        next_check_at=monitor.next_check_at.isoformat() if monitor.next_check_at else None,
    )


@router.delete("/monitors/{monitor_id}", summary="Delete a monitor", operation_id="delete_monitor")
async def delete_monitor(
    monitor_id: str,
    current_user: User = Depends(get_current_mcp_user),
    db: Session = Depends(get_db),
):
    """
    Delete a monitor and cancel pending background checks.
    """
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted",
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    monitor.state = "deleted"
    monitor.is_active = False
    db.commit()

    return {"status": "ok", "message": f"Monitor '{monitor.name}' deleted successfully."}


@router.post("/monitors/{monitor_id}/check", summary="Trigger instant check", operation_id="trigger_check")
async def trigger_check(
    monitor_id: str,
    current_user: User = Depends(get_current_mcp_user),
    db: Session = Depends(get_db),
):
    """
    Trigger an immediate on-demand check for a monitor. ChangeWatch acquires a headless
    browser capture, strips noise, calculates diffs against baseline, and dispatches alerts.
    """
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted",
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    job = enqueue_check(db, monitor.id, is_manual=True)
    if job and (settings.run_inline_checks or settings.is_vercel):
        job.scheduled_at = datetime.now(timezone.utc)
        db.commit()
        await process_check_job(db, job)

    return {
        "status": "enqueued",
        "monitor_id": monitor.id,
        "message": f"Check enqueued for '{monitor.name}' and scheduled for immediate processing.",
    }


@router.get("/monitors/{monitor_id}/diff", response_model=DiffResult, summary="Inspect latest diff", operation_id="get_diff")
async def get_diff(
    monitor_id: str,
    from_version_id: Optional[str] = Query(None, description="Starting version ID (defaults to previous)"),
    to_version_id: Optional[str] = Query(None, description="Ending version ID (defaults to latest)"),
    current_user: User = Depends(get_current_mcp_user),
    db: Session = Depends(get_db),
):
    """
    Get the text unified diff and change metrics between two versions of a monitor.
    Defaults to the latest version vs its preceding version.
    """
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted",
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    all_versions = db.query(Version).filter(
        Version.monitor_id == monitor.id
    ).order_by(Version.version_number.desc()).all()

    if not all_versions:
        raise HTTPException(status_code=404, detail="No captured versions available for this monitor yet.")

    to_ver = next((v for v in all_versions if v.id == to_version_id), all_versions[0])
    from_ver = next((v for v in all_versions if v.id == from_version_id), (all_versions[1] if len(all_versions) > 1 else all_versions[0]))

    diff_items = generate_text_diff(from_ver.normalized_text, to_ver.normalized_text)
    summary = generate_diff_summary(diff_items)

    preview_lines = []
    for item in diff_items[:50]:
        op = "+" if item["type"] == "added" else ("-" if item["type"] == "removed" else " ")
        preview_lines.append(f"{op} {item.get('text', '')}")

    return DiffResult(
        monitor_id=monitor.id,
        from_version_number=from_ver.version_number if from_ver.id != to_ver.id else None,
        to_version_number=to_ver.version_number,
        summary=summary,
        diff_lines_preview=preview_lines,
    )
