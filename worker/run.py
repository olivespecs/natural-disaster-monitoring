"""RQ worker entrypoint — run with: python worker/run.py"""

import sys
import os
import logging

# Ensure project root is on the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis
from rq import Worker, Queue

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    redis_conn = redis.from_url(settings.redis_url)
    queues = [Queue("eonet-inference", connection=redis_conn)]

    logger.info(f"🔧 RQ Worker starting — queues={[q.name for q in queues]}, redis={settings.redis_url}")

    gemini_status = "enabled" if settings.gemini_api_key else "disabled (heuristic fallback)"
    logger.info(f"   Gemini AI: {gemini_status}")

    worker = Worker(queues, connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
