import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models.queue_job import QueueJob
from app.services.queue_service import process_check_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("changewatch.worker")


async def run_worker(poll_interval_seconds: float = 2.0):
    worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    logger.info("ChangeWatch Check Worker %s started; waiting for due jobs", worker_id)
    while True:
        job_id = None
        try:
            with SessionLocal() as db:
                now = datetime.now(timezone.utc)
                # FOR UPDATE SKIP LOCKED is honoured by PostgreSQL; it prevents two
                # replicas from executing the same pending job concurrently.
                job = (
                    db.query(QueueJob)
                    .filter(
                        QueueJob.status == "pending",
                        QueueJob.task_type == "check_monitor",
                        QueueJob.scheduled_at <= now,
                    )
                    .order_by(QueueJob.scheduled_at.asc(), QueueJob.created_at.asc())
                    .with_for_update(skip_locked=True)
                    .first()
                )
                if job:
                    job_id = job.id
                    job.status = "running"
                    job.locked_at = now
                    job.locked_by = worker_id
                    db.commit()
                    logger.info(
                        "Processing job %s for monitor %s (attempt %s/%s)",
                        job.id,
                        job.payload.get("monitor_id"),
                        job.attempts + 1,
                        job.max_attempts,
                    )
                    await process_check_job(db, job)
                    db.expire_all()
                else:
                    await asyncio.sleep(poll_interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Worker loop exception while handling job %s", job_id)
            await asyncio.sleep(min(5.0, poll_interval_seconds + 1.0))


if __name__ == "__main__":
    asyncio.run(run_worker())
