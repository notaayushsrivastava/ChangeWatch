import asyncio
import logging
from app.db import SessionLocal
from app.models.queue_job import QueueJob
from app.services.queue_service import process_check_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("changewatch.worker")


async def run_worker():
    logger.info("ChangeWatch Check Worker started. Listening for queued jobs...")
    while True:
        try:
            with SessionLocal() as db:
                job = db.query(QueueJob).filter(
                    QueueJob.status == "pending",
                    QueueJob.task_type == "check_monitor"
                ).order_by(QueueJob.scheduled_at.asc()).first()

                if job:
                    logger.info("Processing job %s for monitor %s", job.id, job.payload.get("monitor_id"))
                    await process_check_job(db, job)
                else:
                    await asyncio.sleep(2)
        except Exception as e:
            logger.error("Worker loop exception: %s", str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run_worker())
