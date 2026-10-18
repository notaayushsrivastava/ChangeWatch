from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import get_db
from app.models.user import User
from app.models.notification import NotificationChannel
from app.dependencies import get_current_user, get_or_create_csrf_token, validate_csrf
from app.services.security import encrypt_secret, decrypt_secret, mask_secret
from app.services.notifier import send_email_alert, send_discord_webhook_alert

from app.services.oauth import create_access_token
from app.config import settings

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")


def _get_base_url(request: Request) -> str:
    if settings.is_production or (settings.APP_BASE_URL and "changewatch.aayushsrivastava.com" in settings.APP_BASE_URL):
        return "https://changewatch.aayushsrivastava.com"
    if settings.APP_BASE_URL and settings.APP_BASE_URL.startswith("http"):
        return settings.APP_BASE_URL.rstrip("/")
    return str(request.base_url).rstrip("/")


@router.get("", include_in_schema=False)
async def settings_root_redirect():
    return RedirectResponse(url="/settings/notifications", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_settings_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    channels = db.query(NotificationChannel).filter(
        NotificationChannel.user_id == current_user.id
    ).order_by(NotificationChannel.created_at.desc()).all()

    # Decorate masked destinations
    for ch in channels:
        try:
            raw = decrypt_secret(ch.destination)
            ch.masked_destination = mask_secret(raw)
        except Exception:
            ch.masked_destination = "********"

    base_url = _get_base_url(request)
    mcp_server_url = f"{base_url}/mcp"
    sse_server_url = f"{base_url}/sse"
    mcp_token = create_access_token(user_id=current_user.id)

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(request, "settings/notifications.html", {
        "current_user": current_user,
        "csrf_token": csrf_token,
        "channels": channels,
        "mcp_server_url": mcp_server_url,
        "sse_server_url": sse_server_url,
        "mcp_token": mcp_token,
    })


@router.post("/notifications/channels")
async def add_channel_action(
    request: Request,
    label: str = Form(...),
    channel_type: str = Form(...),
    destination: str = Form(...),
    csrf_token: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail="Invalid security token")

    clean_dest = destination.strip()
    if channel_type == "email":
        if "@" not in clean_dest:
            raise HTTPException(status_code=400, detail="Invalid email address format")
    elif channel_type == "discord":
        if not clean_dest.startswith("https://discord.com/api/webhooks/") and not clean_dest.startswith("https://discordapp.com/api/webhooks/"):
            raise HTTPException(status_code=400, detail="Must be a valid Discord webhook URL (https://discord.com/api/webhooks/...)")

    encrypted_dest = encrypt_secret(clean_dest)

    channel = NotificationChannel(
        user_id=current_user.id,
        channel_type=channel_type,
        label=label.strip()[:100],
        destination=encrypted_dest,
        is_enabled=True,
    )
    db.add(channel)
    db.commit()

    return RedirectResponse(url="/settings/notifications", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notifications/channels/{channel_id}/test")
async def test_channel_action(
    channel_id: str,
    request: Request,
    csrf_token: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail="Invalid security token")

    channel = db.query(NotificationChannel).filter(
        NotificationChannel.id == channel_id,
        NotificationChannel.user_id == current_user.id
    ).first()

    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    dest = decrypt_secret(channel.destination)
    success = False
    err = None

    if channel.channel_type == "email":
        success, err = await send_email_alert(
            to_email=dest,
            subject="[ChangeWatch] Test Alert Notification",
            text_content="This is a test alert from ChangeWatch to verify your channel destination works properly."
        )
    elif channel.channel_type == "discord":
        success, err = await send_discord_webhook_alert(
            webhook_url=dest,
            monitor_name="Test Monitor",
            target_url="https://example.com",
            diff_summary="Verified test delivery",
            diff_snippet="+ Test line added\n- Test line removed",
            comparison_url=f"{request.base_url}settings/notifications"
        )

    channel.last_tested_at = datetime.now(timezone.utc)
    channel.last_delivery_status = "success" if success else "failure"
    db.commit()

    return RedirectResponse(url="/settings/notifications", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notifications/channels/{channel_id}/delete")
async def delete_channel_action(
    channel_id: str,
    request: Request,
    csrf_token: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail="Invalid security token")

    channel = db.query(NotificationChannel).filter(
        NotificationChannel.id == channel_id,
        NotificationChannel.user_id == current_user.id
    ).first()

    if channel:
        db.delete(channel)
        db.commit()

    return RedirectResponse(url="/settings/notifications", status_code=status.HTTP_303_SEE_OTHER)
