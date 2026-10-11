import pytest
from unittest.mock import AsyncMock, patch
from app.models.user import User
from app.models.monitor import Monitor
from app.models.version import Version
from app.models.notification import NotificationChannel, AlertEvent, AlertDelivery
from app.services.security import encrypt_secret, decrypt_secret
from app.services.notifier import dispatch_alert_event, send_email_alert


@pytest.mark.asyncio
async def test_alert_dispatch_and_deduplication(db_session):
    user = User(email="notifier@example.com", password_hash="dummy")
    db_session.add(user)
    db_session.commit()

    monitor = Monitor(
        user_id=user.id,
        name="Production Site",
        url="https://example.com",
        interval_minutes=60,
    )
    db_session.add(monitor)
    db_session.commit()

    channel = NotificationChannel(
        user_id=user.id,
        channel_type="email",
        label="Primary Email",
        destination=encrypt_secret("alerts@example.com"),
        is_enabled=True,
    )
    db_session.add(channel)
    db_session.commit()

    version = Version(
        monitor_id=monitor.id,
        version_number=2,
        content_hash="abc123hash",
        normalized_text="New text",
        reason="content_changed",
    )
    db_session.add(version)
    db_session.commit()

    alert_event = AlertEvent(
        monitor_id=monitor.id,
        version_id=version.id,
        dedupe_key=f"{monitor.id}:{version.id}",
        summary="1 addition, 0 deletions",
        diff_snippet="+ New text",
    )
    db_session.add(alert_event)
    db_session.commit()

    # First dispatch should deliver and create 1 AlertDelivery
    with patch("app.services.notifier.send_email_alert", new=AsyncMock(return_value=(True, None))):
        await dispatch_alert_event(db_session, alert_event, "http://localhost:8000/diff")

    deliveries = db_session.query(AlertDelivery).filter(AlertDelivery.alert_event_id == alert_event.id).all()
    assert len(deliveries) == 1
    assert deliveries[0].status == "sent"
    assert deliveries[0].attempt_count == 1

    # Second dispatch for same event and channel should be a no-op (idempotent deduplication)
    with patch("app.services.notifier.send_email_alert", new=AsyncMock(return_value=(True, None))):
        await dispatch_alert_event(db_session, alert_event, "http://localhost:8000/diff")

    deliveries_after = db_session.query(AlertDelivery).filter(AlertDelivery.alert_event_id == alert_event.id).all()
    assert len(deliveries_after) == 1
    assert deliveries_after[0].attempt_count == 1


def test_secret_encryption_and_masking():
    secret_webhook = "https://discord.com/api/webhooks/1234567890/abc-secret-token"
    encrypted = encrypt_secret(secret_webhook)
    assert encrypted != secret_webhook

    decrypted = decrypt_secret(encrypted)
    assert decrypted == secret_webhook
