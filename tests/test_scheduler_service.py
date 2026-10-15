from datetime import datetime, timedelta, timezone

from app.models.monitor import Monitor
from app.models.queue_job import QueueJob
from app.models.user import User
from app.services.scheduler_service import recover_stale_jobs, run_scheduler_tick


def create_user_and_monitor(db_session, *, next_check_at=None):
    user = User(email=f"scheduler-{datetime.now(timezone.utc).timestamp()}@example.invalid", password_hash="unused")
    db_session.add(user)
    db_session.commit()
    monitor = Monitor(
        user_id=user.id,
        name="Scheduler test",
        url="https://example.com/",
        interval_minutes=60,
        state="active",
        next_check_at=next_check_at,
    )
    db_session.add(monitor)
    db_session.commit()
    return user, monitor


def test_scheduler_enqueues_active_monitor_without_first_check(db_session):
    _, monitor = create_user_and_monitor(db_session)

    count = run_scheduler_tick(db_session)

    assert count == 1
    job = db_session.query(QueueJob).filter(
        QueueJob.task_type == "check_monitor",
        QueueJob.payload_json.like(f'%"monitor_id": "{monitor.id}"%'),
    ).first()
    assert job is not None
    assert job.status == "pending"
    assert job.payload["monitor_id"] == monitor.id

    # Repeated ticks coalesce; they must not flood the queue with duplicate jobs.
    assert run_scheduler_tick(db_session) == 0
    assert db_session.query(QueueJob).filter(
        QueueJob.task_type == "check_monitor",
        QueueJob.payload_json.like(f'%"monitor_id": "{monitor.id}"%'),
    ).count() == 1


def test_scheduler_recovers_stale_running_job_and_preserves_retry(db_session):
    _, monitor = create_user_and_monitor(db_session)
    now = datetime.now(timezone.utc)
    job = QueueJob(
        task_type="check_monitor",
        payload={"monitor_id": monitor.id},
        status="running",
        attempts=1,
        max_attempts=3,
        locked_at=now - timedelta(minutes=20),
        created_at=now - timedelta(minutes=25),
        scheduled_at=now - timedelta(minutes=25),
    )
    db_session.add(job)
    db_session.commit()

    recovered = recover_stale_jobs(db_session, now=now)
    db_session.refresh(job)
    db_session.refresh(monitor)

    assert recovered == 1
    assert job.status == "pending"
    assert job.locked_at is None
    scheduled_at = job.scheduled_at
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    next_check_at = monitor.next_check_at
    if next_check_at.tzinfo is None:
        next_check_at = next_check_at.replace(tzinfo=timezone.utc)
    assert scheduled_at > now
    assert monitor.last_error_code == "WORKER_TIMEOUT"
    assert next_check_at > now


def test_scheduler_marks_exhausted_stale_job_failed(db_session):
    _, monitor = create_user_and_monitor(db_session)
    now = datetime.now(timezone.utc)
    job = QueueJob(
        task_type="check_monitor",
        payload={"monitor_id": monitor.id},
        status="running",
        attempts=3,
        max_attempts=3,
        locked_at=now - timedelta(minutes=20),
        created_at=now - timedelta(minutes=25),
        scheduled_at=now - timedelta(minutes=25),
    )
    db_session.add(job)
    db_session.commit()

    assert recover_stale_jobs(db_session, now=now) == 1
    db_session.refresh(job)
    db_session.refresh(monitor)
    assert job.status == "failed"
    assert monitor.last_status == "error"
    assert monitor.last_error_code == "WORKER_TIMEOUT"
