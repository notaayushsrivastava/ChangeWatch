import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.monitor import Monitor
from app.models.queue_job import QueueJob
from app.models.check_run import CheckRun
from app.services.queue_service import enqueue_check

logger = logging.getLogger("changewatch.scheduler")

STALE_JOB_AFTER = timedelta(minutes=10)


def recover_stale_jobs(db: Session, now: datetime | None = None) -> int:
    """Requeue or fail jobs orphaned by a worker/serverless process dying mid-capture."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - STALE_JOB_AFTER
    stale_jobs = (
        db.query(QueueJob)
        .filter(
            QueueJob.task_type == "check_monitor",
            QueueJob.status == "running",
            or_(QueueJob.locked_at <= cutoff, QueueJob.locked_at.is_(None) & (QueueJob.created_at <= cutoff)),
        )
        .with_for_update(skip_locked=True)
        .all()
    )

    recovered = 0
    for job in stale_jobs:
        payload = job.payload
        monitor_id = payload.get("monitor_id")
        monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
        run = (
            db.query(CheckRun)
            .filter(CheckRun.monitor_id == monitor_id, CheckRun.status == "running")
            .order_by(CheckRun.started_at.desc())
            .first()
        )
        if run:
            run.status = "error"
            run.finished_at = now
            run.failure_code = "WORKER_TIMEOUT"
            run.safe_error_message = "The browser worker stopped before finishing this check."

        job.locked_at = None
        job.locked_by = None
        if job.attempts < job.max_attempts:
            job.status = "pending"
            job.scheduled_at = now + timedelta(seconds=min(300, 5 * (2 ** max(0, job.attempts - 1))))
            job.error_message = "The previous worker attempt was interrupted; this check will retry."
            if monitor:
                monitor.last_status = "pending"
                monitor.last_error_code = "WORKER_TIMEOUT"
                monitor.last_error_message = job.error_message
        else:
            job.status = "failed"
            job.completed_at = now
            job.error_message = "The browser worker repeatedly stopped before finishing this check."
            if monitor:
                monitor.last_status = "error"
                monitor.last_error_code = "WORKER_TIMEOUT"
                monitor.last_error_message = job.error_message
                monitor.last_checked_at = now
        if monitor:
            monitor.next_check_at = now + timedelta(minutes=max(15, monitor.interval_minutes))
        recovered += 1

    if recovered:
        db.commit()
        logger.warning("Recovered %d stale monitor job(s)", recovered)
    return recovered


def run_scheduler_tick(db: Session) -> int:
    """Recover orphaned jobs, then enqueue all active monitors whose next check is due."""
    now = datetime.now(timezone.utc)
    recover_stale_jobs(db, now=now)

    due_monitors = (
        db.query(Monitor)
        .filter(
            Monitor.state == "active",
            or_(Monitor.next_check_at <= now, Monitor.next_check_at.is_(None)),
        )
        .order_by(Monitor.next_check_at.asc().nullsfirst(), Monitor.created_at.asc())
        .all()
    )

    enqueued_count = 0
    for monitor in due_monitors:
        before = (
            db.query(QueueJob.id)
            .filter(
                QueueJob.task_type == "check_monitor",
                QueueJob.status.in_(["pending", "running"]),
                QueueJob.payload_json.like(f'%"monitor_id": "{monitor.id}"%'),
            )
            .first()
        )
        job = enqueue_check(db, monitor.id)
        if job and before is None:
            enqueued_count += 1
    return enqueued_count


async def scheduler_loop(interval_seconds: int = 30):
    """Continuous async loop for the persistent scheduler process."""
    logger.info("Starting ChangeWatch scheduler loop...")
    while True:
        try:
            with SessionLocal() as db:
                count = run_scheduler_tick(db)
                if count > 0:
                    logger.info("Enqueued %d due monitor check(s)", count)
        except Exception:
            logger.exception("Error during scheduler tick")
        await asyncio.sleep(interval_seconds)
