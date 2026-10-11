import asyncio
import logging
from app.services.scheduler_service import scheduler_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


if __name__ == "__main__":
    asyncio.run(scheduler_loop(interval_seconds=30))
