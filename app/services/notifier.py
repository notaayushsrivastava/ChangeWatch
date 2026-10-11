import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import httpx
from sqlalchemy.orm import Session
from app.config import settings
from app.models.notification import NotificationChannel, AlertEvent, AlertDelivery
from app.services.security import decrypt_secret
from app.services.url_safety import validate_public_url

logger = logging.getLogger("changewatch.notifier")


async def send_email_alert(
    to_email: str,
    subject: str,
    text_content: str,
    html_content: Optional[str] = None
) -> tuple[bool, Optional[str]]:
    """Sends email via console logging, SMTP, or Resend."""
    if settings.EMAIL_PROVIDER == "console":
        print("\n" + "="*50)
        print(f"[CONSOLE EMAIL ALERT]")
        print(f"To: {to_email}")
        print(f"Subject: {subject}")
        print(f"Content:\n{text_content}")
        print("="*50 + "\n")
        return True, None

    elif settings.EMAIL_PROVIDER == "smtp":
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.EMAIL_FROM
            msg["To"] = to_email
            msg.attach(MIMEText(text_content, "plain"))
            if html_content:
                msg.attach(MIMEText(html_content, "html"))

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                if settings.SMTP_USE_TLS:
                    server.starttls()
                if settings.SMTP_USER and settings.SMTP_PASSWORD:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            return True, None
        except Exception as e:
            logger.error("SMTP error: %s", str(e))
            return False, f"SMTP error: {str(e)}"

    elif settings.EMAIL_PROVIDER == "resend":
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                    json={
                        "from": settings.EMAIL_FROM,
                        "to": [to_email],
                        "subject": subject,
                        "text": text_content,
                        "html": html_content or f"<pre>{text_content}</pre>",
                    }
                )
                if res.status_code in (200, 201):
                    return True, None
                return False, f"Resend API error: {res.status_code} {res.text}"
        except Exception as e:
            return False, f"Resend connection failed: {str(e)}"

    return False, "Unknown email provider"


async def send_discord_webhook_alert(
    webhook_url: str,
    monitor_name: str,
    target_url: str,
    diff_summary: str,
    diff_snippet: Optional[str],
    comparison_url: str,
) -> tuple[bool, Optional[str]]:
    """Sends rich Discord embed alert with SSRF verification."""
    # Ensure webhook is a valid public Discord destination
    if not webhook_url.startswith("https://discord.com/api/webhooks/") and not webhook_url.startswith("https://discordapp.com/api/webhooks/"):
        return False, "Invalid Discord webhook URL format"

    is_safe, _, _ = validate_public_url(webhook_url)
    if not is_safe:
        return False, "Discord destination failed SSRF safety check"

    # Truncate diff snippet for Discord embed limits
    snippet_text = diff_snippet[:1500] if diff_snippet else "Visit dashboard to view the visual and text diff."

    payload = {
        "embeds": [
            {
                "title": f"🔔 Change Detected: {monitor_name}",
                "description": f"A meaningful content change was detected on **{target_url}**.",
                "color": 3447003,  # Blue
                "fields": [
                    {
                        "name": "Change Summary",
                        "value": diff_summary or "Content updated",
                        "inline": False,
                    },
                    {
                        "name": "Diff Preview",
                        "value": f"```diff\n{snippet_text}\n```",
                        "inline": False,
                    },
                    {
                        "name": "Comparison Link",
                        "value": f"[View Full Diff]({comparison_url})",
                        "inline": False,
                    }
                ],
                "footer": {
                    "text": "ChangeWatch Monitor Alert"
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code in (200, 204):
                return True, None
            return False, f"Discord returned HTTP {resp.status_code}"
    except Exception as e:
        return False, f"Webhook delivery error: {str(e)}"


async def dispatch_alert_event(
    db: Session,
    alert_event: AlertEvent,
    comparison_url: str
) -> None:
    """Dispatches an alert event to all active user notification channels with deduplication."""
    monitor = alert_event.monitor
    if not monitor:
        return

    channels = db.query(NotificationChannel).filter(
        NotificationChannel.user_id == monitor.user_id,
        NotificationChannel.is_enabled == True
    ).all()

    for ch in channels:
        dedupe_key = f"{alert_event.id}:{ch.id}"
        existing = db.query(AlertDelivery).filter(AlertDelivery.dedupe_key == dedupe_key).first()
        if existing and existing.status == "sent":
            continue

        delivery = existing or AlertDelivery(
            alert_event_id=alert_event.id,
            channel_id=ch.id,
            dedupe_key=dedupe_key,
            status="queued",
            attempt_count=0
        )
        if not existing:
            db.add(delivery)
        db.commit()

        # Decrypt destination secret
        destination = decrypt_secret(ch.destination)
        delivery.attempt_count += 1
        delivery.last_attempt_at = datetime.now(timezone.utc)

        success = False
        err_msg = None

        if ch.channel_type == "email":
            subject = f"[ChangeWatch] Change detected on {monitor.name}"
            body = (
                f"A meaningful change was detected on {monitor.name} ({monitor.url}).\n\n"
                f"Summary: {alert_event.summary}\n\n"
                f"Preview:\n{alert_event.diff_snippet or 'N/A'}\n\n"
                f"Compare versions here: {comparison_url}\n"
            )
            success, err_msg = await send_email_alert(destination, subject, body)

        elif ch.channel_type == "discord":
            success, err_msg = await send_discord_webhook_alert(
                webhook_url=destination,
                monitor_name=monitor.name,
                target_url=monitor.url,
                diff_summary=alert_event.summary,
                diff_snippet=alert_event.diff_snippet,
                comparison_url=comparison_url
            )

        if success:
            delivery.status = "sent"
            delivery.sent_at = datetime.now(timezone.utc)
            ch.last_delivery_status = "success"
        else:
            delivery.status = "retryable_failure" if delivery.attempt_count < 3 else "permanent_failure"
            delivery.provider_error_message = err_msg
            ch.last_delivery_status = "failure"

        ch.last_tested_at = datetime.now(timezone.utc)
        db.commit()
