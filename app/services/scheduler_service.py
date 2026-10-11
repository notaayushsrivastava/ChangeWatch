import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models.monitor import Monitor
from app.services.queue_service import enqueue_check

logger = logging.getLogger("changewatch.scheduler")


def run_scheduler_tick(db: Session) -> int:
    """Finds all active monitors due for a check and enqueues them."""
    now = datetime.now(timezone.utc)
    due_monitors = db.query(Monitor).filter(
        Monitor.state == "active",
        (Monitor.next_check_at <= now) | (Monitor.next_check_at == None)
    ).all()

    enqueued_count = 0
    for mon in due_monitors:
        enqueue_check(db, mon.id)
        enqueued_count += 1

    return enqueued_count


async def scheduler_loop(interval_seconds: int = 30):
    """Continuous async loop for the scheduler process."""
    logger.info("Starting ChangeWatch scheduler loop...")
    while True:
        try:
            with SessionLocal() as db:
                count = run_scheduler_tick(db)
                if count > 0:
                    logger.info("Enqueued %d due monitor check(s)", count)
        except Exception as e:
            logger.error("Error during scheduler tick: %s", str(e))

        await asyncio.sleep(interval_seconds)
