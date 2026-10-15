from datetime import datetime, timezone

from app.config import settings
from app.models.monitor import Monitor
from app.models.queue_job import QueueJob
from app.models.user import User
from app.services.browser_capture import CaptureResult, browser_capture_service


def test_worker_tick_rejects_requests_without_authorization(client, monkeypatch):
    monkeypatch.setattr(settings, "CRON_SECRET", "x" * 40)

    response = client.get("/internal/worker/tick")

    assert response.status_code == 401


def test_worker_tick_processes_initial_job_instead_of_leaving_it_pending(client, db_session, monkeypatch):
    token = "scheduler-test-token-012345678901234567890123456"
    monkeypatch.setattr(settings, "CRON_SECRET", token)

    user = User(email="worker-tick@example.invalid", password_hash="unused")
    db_session.add(user)
    db_session.commit()
    monitor = Monitor(
        user_id=user.id,
        name="First check",
        url="https://example.com/",
        interval_minutes=60,
        state="active",
        next_check_at=None,
    )
    db_session.add(monitor)
    db_session.commit()

    async def missing_browser_backend(**kwargs):
        return CaptureResult(
            success=False,
            failure_code="BROWSER_WORKER_UNCONFIGURED",
            error_message="Configure a remote browser provider.",
            duration_ms=2,
        )

    monkeypatch.setattr(browser_capture_service, "capture_page", missing_browser_backend)
    response = client.get(
        "/internal/worker/tick",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] is True
    assert payload["check_succeeded"] is False
    assert payload["job_status"] == "failed"
    assert payload["monitor_status"] == "error"

    db_session.refresh(monitor)
    job = db_session.query(QueueJob).filter(
        QueueJob.task_type == "check_monitor",
        QueueJob.payload_json.like(f'%"monitor_id": "{monitor.id}"%'),
    ).first()
    assert monitor.last_status == "error"
    assert monitor.last_error_code == "BROWSER_WORKER_UNCONFIGURED"
    assert job.status == "failed"
    assert job.completed_at is not None


def test_worker_tick_requires_configuration(client, monkeypatch):
    monkeypatch.setattr(settings, "CRON_SECRET", "")

    response = client.get(
        "/internal/worker/tick",
        headers={"Authorization": "Bearer anything"},
    )

    assert response.status_code == 503
