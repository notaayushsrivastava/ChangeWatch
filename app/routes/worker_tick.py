"""Authenticated queue/scheduler tick for serverless deployments.

A Vercel function is not a resident worker. This endpoint runs one due monitor
check per invocation and is intended to be called by an external scheduler such
as the included GitHub Actions workflow. A persistent container worker remains
better for high-volume monitoring.
"""
import hmac
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.monitor import Monitor
from app.models.queue_job import QueueJob
from app.services.queue_service import process_check_job
from app.services.scheduler_service import run_scheduler_tick

router = APIRouter()
logger = logging.getLogger("changewatch.scheduler.endpoint")


def _authorized(authorization: str | None) -> bool:
    expected = settings.CRON_SECRET.strip()
    if len(expected) < 32:
        return False
    scheme, _, supplied = (authorization or "").partition(" ")
    return (
        scheme.lower() == "bearer"
        and bool(supplied)
        and hmac.compare_digest(supplied, expected)
    )


@router.get("/internal/worker/tick", include_in_schema=False)
async def worker_tick(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Enqueue due monitors, then safely claim and process at most one queue job."""
    if len(settings.CRON_SECRET.strip()) < 32:
        raise HTTPException(
            status_code=503,
            detail="Scheduled worker is not configured; set CRON_SECRET to a random value of at least 32 characters.",
        )
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="Invalid scheduler credentials.")

    enqueued = run_scheduler_tick(db)
    now = datetime.now(timezone.utc)
    job = (
        db.query(QueueJob)
        .filter(
            QueueJob.task_type == "check_monitor",
            QueueJob.status == "pending",
            QueueJob.scheduled_at <= now,
        )
        .order_by(QueueJob.scheduled_at.asc(), QueueJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )

    if job is None:
        return {
            "ok": True,
            "enqueued": enqueued,
            "processed": False,
            "message": "No due monitor jobs.",
        }

    job_id = job.id
    monitor_id = job.payload.get("monitor_id")
    job.status = "running"
    job.locked_at = now
    job.locked_by = f"serverless-tick-{uuid.uuid4().hex[:12]}"
    db.commit()

    success = await process_check_job(db, job)
    db.expire_all()

    refreshed_job = db.query(QueueJob).filter(QueueJob.id == job_id).first()
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
    return {
        "ok": True,
        "enqueued": enqueued,
        "processed": True,
        "job_id": job_id,
        "job_status": refreshed_job.status if refreshed_job else "unknown",
        "monitor_status": monitor.last_status if monitor else "deleted",
        "check_succeeded": success,
    }
