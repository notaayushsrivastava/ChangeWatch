import io
import pytest
from unittest.mock import AsyncMock, patch
from PIL import Image
from app.models.user import User
from app.models.monitor import Monitor
from app.models.version import Version
from app.models.check_run import CheckRun
from app.models.queue_job import QueueJob
from app.models.notification import AlertEvent, NotificationChannel, AlertDelivery
from app.services.browser_capture import CaptureResult
from app.services.queue_service import enqueue_check, process_check_job


def create_dummy_png():
    img = Image.new("RGB", (50, 50), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_full_check_lifecycle_and_versioning(db_session):
    # 1. Create User and Monitor
    user = User(email="e2e@example.com", password_hash="dummy")
    db_session.add(user)
    db_session.commit()

    monitor = Monitor(
        user_id=user.id,
        name="Changelog Watcher",
        url="https://example.com/changelog",
        interval_minutes=60,
        sensitivity="medium",
        state="active"
    )
    db_session.add(monitor)
    db_session.commit()

    dummy_png = create_dummy_png()

    # 2. First Run: Baseline Creation
    mock_capture_1 = CaptureResult(
        success=True,
        raw_text="Changelog:\nVersion 1.0 released yesterday.",
        screenshot_bytes=dummy_png,
        http_status=200,
        duration_ms=450,
    )

    with patch("app.services.queue_service.browser_capture_service.capture_page", new=AsyncMock(return_value=mock_capture_1)):
        job1 = enqueue_check(db_session, monitor.id, is_manual=True)
        assert job1 is not None
        success = await process_check_job(db_session, job1)
        assert success

    db_session.refresh(monitor)
    assert monitor.last_status == "ok"
    assert monitor.last_version_id is not None

    versions = db_session.query(Version).filter(Version.monitor_id == monitor.id).all()
    assert len(versions) == 1
    assert versions[0].reason == "baseline"
    assert versions[0].version_number == 1

    # Baseline should NOT generate any alert events
    alerts = db_session.query(AlertEvent).filter(AlertEvent.monitor_id == monitor.id).all()
    assert len(alerts) == 0

    # 3. Second Run: Unchanged Content
    mock_capture_2 = CaptureResult(
        success=True,
        raw_text="Changelog:\nVersion 1.0 released today.",  # "today" is volatile noise, should normalize identically!
        screenshot_bytes=dummy_png,
        http_status=200,
        duration_ms=420,
    )

    with patch("app.services.queue_service.browser_capture_service.capture_page", new=AsyncMock(return_value=mock_capture_2)):
        job2 = enqueue_check(db_session, monitor.id, is_manual=True)
        assert job2 is not None
        success = await process_check_job(db_session, job2)
        assert success

    versions = db_session.query(Version).filter(Version.monitor_id == monitor.id).all()
    assert len(versions) == 1  # Unchanged check retains store-on-change policy: NO new version!

    runs = db_session.query(CheckRun).filter(CheckRun.monitor_id == monitor.id).all()
    assert len(runs) == 2
    assert runs[-1].changed is False

    # 4. Third Run: Meaningful Change Detected
    mock_capture_3 = CaptureResult(
        success=True,
        raw_text="Changelog:\nVersion 1.0 released.\nVersion 2.0 released with exciting new features!",
        screenshot_bytes=dummy_png,
        http_status=200,
        duration_ms=490,
    )

    with patch("app.services.queue_service.browser_capture_service.capture_page", new=AsyncMock(return_value=mock_capture_3)):
        job3 = enqueue_check(db_session, monitor.id, is_manual=True)
        assert job3 is not None
        success = await process_check_job(db_session, job3)
        assert success

    db_session.refresh(monitor)
    versions = db_session.query(Version).filter(Version.monitor_id == monitor.id).order_by(Version.version_number.asc()).all()
    assert len(versions) == 2
    assert versions[1].reason == "content_changed"
    assert versions[1].version_number == 2

    # Verify alert event was recorded with unique dedupe key
    alerts = db_session.query(AlertEvent).filter(AlertEvent.monitor_id == monitor.id).all()
    assert len(alerts) == 1
    assert alerts[0].dedupe_key == f"{monitor.id}:{versions[1].id}"
