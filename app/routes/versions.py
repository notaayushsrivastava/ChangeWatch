from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import get_db
from app.models.user import User
from app.models.monitor import Monitor
from app.models.version import Version
from app.dependencies import get_current_user, get_or_create_csrf_token
from app.services.diff_engine import generate_text_diff, generate_diff_summary, generate_visual_diff
from app.services.artifact_storage import artifact_storage

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/monitors/{monitor_id}/diff", response_class=HTMLResponse)
async def version_diff_page(
    monitor_id: str,
    request: Request,
    from_id: Optional[str] = Query(None, alias="from"),
    to_id: Optional[str] = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted"
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    all_versions = db.query(Version).filter(
        Version.monitor_id == monitor.id
    ).order_by(Version.version_number.desc()).all()

    if not all_versions:
        raise HTTPException(status_code=404, detail="No versions found for this monitor")

    # Select target versions
    if to_id:
        to_version = next((v for v in all_versions if v.id == to_id), all_versions[0])
    else:
        to_version = all_versions[0]

    if from_id:
        from_version = next((v for v in all_versions if v.id == from_id), (all_versions[1] if len(all_versions) > 1 else all_versions[0]))
    else:
        from_version = all_versions[1] if len(all_versions) > 1 else all_versions[0]

    # Generate text diff
    diff_items = generate_text_diff(from_version.normalized_text, to_version.normalized_text)
    summary = generate_diff_summary(diff_items)

    # Check for visual diff image or compute on-the-fly
    diff_artifact_key = None
    if from_version.screenshot_artifact_key and to_version.screenshot_artifact_key:
        expected_diff_filename = f"diff_{monitor.id}_{from_version.id}_{to_version.id}.png"
        existing_artifact = artifact_storage.exists(expected_diff_filename)

        if existing_artifact:
            diff_artifact_key = expected_diff_filename
        else:
            # Generate visual diff
            b1 = artifact_storage.read_bytes(from_version.screenshot_artifact_key)
            b2 = artifact_storage.read_bytes(to_version.screenshot_artifact_key)
            if b1 and b2:
                try:
                    diff_png, _ = generate_visual_diff(b1, b2)
                    diff_artifact_key = artifact_storage.save_diff_image(diff_png, monitor.id, f"{from_version.id}_{to_version.id}")
                except Exception:
                    pass

    csrf_token = get_or_create_csrf_token(request)

    return templates.TemplateResponse(request, "versions/diff.html", {
        "current_user": current_user,
        "csrf_token": csrf_token,
        "monitor": monitor,
        "all_versions": all_versions,
        "from_version": from_version,
        "to_version": to_version,
        "diff_items": diff_items,
        "summary": summary,
        "diff_artifact_key": diff_artifact_key,
    })


@router.get("/artifacts/{filename}")
async def serve_artifact(
    filename: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Securely serves PNG screenshot or diff artifact."""
    data = artifact_storage.read_bytes(filename)
    if not data:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return Response(content=data, media_type="image/png", headers={
        "Cache-Control": "private, max-age=86400",
        "X-Content-Type-Options": "nosniff",
    })
