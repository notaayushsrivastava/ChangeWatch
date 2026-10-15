from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.monitor import Monitor
from app.models.queue_job import QueueJob
from app.models.user import User
from app.models.version import Version
from app.models.check_run import CheckRun
from app.services.browser_capture import CaptureResult, browser_capture_service
from app.services.artifact_storage import artifact_storage
from app.services.queue_service import process_check_job


def create_monitor_job(db_session, email):
    user = User(email=email, password_hash="unused")
    db_session.add(user)
    db_session.commit()
    monitor = Monitor(
        user_id=user.id,
        name="Queue regression",
        url="https://example.com/",
        interval_minutes=60,
        state="active",
    )
    db_session.add(monitor)
    db_session.commit()
    job = QueueJob(
        task_type="check_monitor",
        payload={"monitor_id": monitor.id, "is_manual": True},
        status="pending",
        scheduled_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    db_session.commit()
    return monitor, job


@pytest.mark.asyncio
async def test_text_baseline_succeeds_if_optional_screenshot_storage_fails(db_session, monkeypatch):
    monitor, job = create_monitor_job(db_session, "queue-storage@example.invalid")

    async def fake_capture(**kwargs):
        return CaptureResult(
            success=True,
            raw_text="Page is live and has a stable baseline.",
            screenshot_bytes=b"fake-png",
            http_status=200,
            duration_ms=10,
            metadata={"browser": "test"},
        )

    def storage_unavailable(*args, **kwargs):
        raise RuntimeError("object storage is not configured")

    monkeypatch.setattr(browser_capture_service, "capture_page", fake_capture)
    monkeypatch.setattr(artifact_storage, "save_screenshot", storage_unavailable)
    monkeypatch.delenv("VERCEL", raising=False)

    succeeded = await process_check_job(db_session, job)

    db_session.refresh(monitor)
    db_session.refresh(job)
    version = db_session.query(Version).filter(Version.monitor_id == monitor.id).one()
    check_run = db_session.query(CheckRun).filter(CheckRun.monitor_id == monitor.id).one()

    assert succeeded is True
    assert monitor.last_status == "ok"
    assert monitor.last_version_id == version.id
    assert version.screenshot_artifact_key is None
    assert check_run.status == "ok"
    assert job.status == "completed"


@pytest.mark.asyncio
async def test_unexpected_capture_exception_requeues_job_instead_of_leaving_running(db_session, monkeypatch):
    # Use a savepoint session so the processor's deliberate rollback on an
    # exception doesn't roll back the fixture's outer transaction.
    session = Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")
    try:
        monitor, job = create_monitor_job(session, "queue-exception@example.invalid")

        async def broken_capture(**kwargs):
            raise RuntimeError("simulated browser crash")

        monkeypatch.setattr(browser_capture_service, "capture_page", broken_capture)
        monkeypatch.delenv("VERCEL", raising=False)

        succeeded = await process_check_job(session, job)

        session.refresh(monitor)
        session.refresh(job)
        check_run = session.query(CheckRun).filter(CheckRun.monitor_id == monitor.id).one()

        scheduled_at = job.scheduled_at
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

        assert succeeded is False
        assert job.status == "pending"
        assert job.locked_at is None
        assert scheduled_at > datetime.now(timezone.utc)
        assert monitor.last_status == "pending"
        assert monitor.last_error_code == "WORKER_EXCEPTION"
        assert check_run.status == "error"
        assert check_run.failure_code == "WORKER_EXCEPTION"
    finally:
        session.close()
