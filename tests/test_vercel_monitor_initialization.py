from datetime import datetime, timezone

from app.models.monitor import Monitor
from app.models.queue_job import QueueJob
from app.models.user import User
from app.models.version import Version
from app.services.browser_capture import CaptureResult, browser_capture_service
from app.services.security import create_session_token, generate_csrf_token
import app.routes.monitors as monitor_routes


def test_vercel_monitor_creation_runs_initial_check_inline(client, db_session, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setattr(
        monitor_routes,
        "validate_public_url",
        lambda url: (True, url, None),
    )

    async def successful_capture(**kwargs):
        return CaptureResult(
            success=True,
            raw_text="ChangeWatch initial baseline created successfully.",
            screenshot_bytes=b"",
            http_status=200,
            duration_ms=5,
            metadata={"browser": "test"},
        )

    monkeypatch.setattr(browser_capture_service, "capture_page", successful_capture)

    user = User(email="vercel-inline-baseline@example.invalid", password_hash="unused")
    db_session.add(user)
    db_session.commit()
    session_token = create_session_token(user.id)
    client.cookies.set("cw_session", session_token)
    csrf_token = generate_csrf_token(session_token)

    response = client.post(
        "/monitors/new",
        data={
            "csrf_token": csrf_token,
            "name": "Inline first check",
            "url": "https://example.com/",
            "interval_minutes": 60,
            "sensitivity": "medium",
            "keywords": "",
            "numeric_selector": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    monitor = db_session.query(Monitor).filter(
        Monitor.user_id == user.id,
        Monitor.name == "Inline first check",
    ).one()
    job = db_session.query(QueueJob).filter(
        QueueJob.task_type == "check_monitor",
        QueueJob.payload_json.like(f'%"monitor_id": "{monitor.id}"%'),
    ).one()
    version = db_session.query(Version).filter(Version.monitor_id == monitor.id).one()

    assert monitor.last_status == "ok"
    assert monitor.last_version_id == version.id
    assert version.reason == "baseline"
    assert monitor.last_checked_at is not None
    assert monitor.next_check_at is not None
    assert job.status == "completed"
    assert job.completed_at is not None
