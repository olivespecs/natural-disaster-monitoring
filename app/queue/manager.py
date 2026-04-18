"""Queue management layer — thin wrapper over Redis + RQ."""

import json
import logging
from datetime import datetime
from typing import List, Optional

import redis
from rq import Queue
from rq.job import Job

from app.config import settings
from app.models import EONETEvent, QueueStats

logger = logging.getLogger(__name__)

# Shared Redis connection
redis_conn = redis.from_url(settings.redis_url, decode_responses=False)

# The single inference queue
inference_queue = Queue("eonet-inference", connection=redis_conn)

SEEN_EVENTS_KEY = "eonet:seen_events"
ENRICHED_EVENT_PREFIX = "eonet:event:"
ENRICHED_EVENT_TTL = 60 * 60 * 24  # 24 hours


# ── Seen-event deduplication ─────────────────────────────────────────────────

async def get_seen_event_ids() -> set:
    """Return the set of event IDs already enqueued/processed."""
    try:
        members = redis_conn.smembers(SEEN_EVENTS_KEY)
        return {m.decode() for m in members}
    except Exception as e:
        logger.error(f"Failed to read seen events: {e}")
        return set()


async def mark_event_seen(event_id: str) -> None:
    """Mark an event ID as seen so it won't be re-enqueued."""
    try:
        redis_conn.sadd(SEEN_EVENTS_KEY, event_id)
        redis_conn.expire(SEEN_EVENTS_KEY, 60 * 60 * 24 * 7)  # 7-day TTL
    except Exception as e:
        logger.error(f"Failed to mark event seen: {e}")


# ── Event enqueuing ──────────────────────────────────────────────────────────

async def enqueue_event(event: EONETEvent) -> str:
    """Enqueue an EONET event for AI inference. Returns the RQ job ID."""
    from app.queue.worker_tasks import process_event_task  # avoid circular import

    job = inference_queue.enqueue(
        process_event_task,
        event.model_dump(),
        job_timeout=120,
        result_ttl=ENRICHED_EVENT_TTL,
        failure_ttl=ENRICHED_EVENT_TTL,
    )

    # Store initial enriched-event record in Redis
    initial = {
        "event": event.model_dump(),
        "inference": None,
        "job_id": job.id,
        "status": "queued",
        "queued_at": datetime.utcnow().isoformat(),
        "completed_at": None,
    }
    redis_conn.setex(
        f"{ENRICHED_EVENT_PREFIX}{event.id}",
        ENRICHED_EVENT_TTL,
        json.dumps(initial, default=str),
    )
    logger.debug(f"Enqueued event {event.id} → job {job.id}")
    return job.id


# ── Event retrieval ──────────────────────────────────────────────────────────

def get_enriched_event(event_id: str) -> Optional[dict]:
    """Retrieve a single enriched event record from Redis."""
    raw = redis_conn.get(f"{ENRICHED_EVENT_PREFIX}{event_id}")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


def update_enriched_event(event_id: str, data: dict) -> None:
    """Persist an updated enriched-event record to Redis."""
    redis_conn.setex(
        f"{ENRICHED_EVENT_PREFIX}{event_id}",
        ENRICHED_EVENT_TTL,
        json.dumps(data, default=str),
    )


def get_all_enriched_events() -> List[dict]:
    """Return all enriched event records, sorted newest-first."""
    keys = redis_conn.keys(f"{ENRICHED_EVENT_PREFIX}*")
    events: List[dict] = []
    for key in keys:
        raw = redis_conn.get(key)
        if raw:
            try:
                events.append(json.loads(raw))
            except Exception:
                pass
    events.sort(key=lambda x: x.get("queued_at", ""), reverse=True)
    return events


# ── Queue stats ──────────────────────────────────────────────────────────────

def get_queue_stats() -> QueueStats:
    """Return live queue depth and worker stats."""
    try:
        from rq import Worker
        workers = Worker.all(connection=redis_conn)
        return QueueStats(
            queued=inference_queue.count,
            started=inference_queue.started_job_registry.count,
            finished=inference_queue.finished_job_registry.count,
            failed=inference_queue.failed_job_registry.count,
            workers=len(workers),
            events_per_minute=0.0,
        )
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        return QueueStats(queued=0, started=0, finished=0, failed=0, workers=0, events_per_minute=0.0)
