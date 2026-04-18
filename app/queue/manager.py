"""Queue management layer — thin wrapper over Redis + RQ."""

import json
import logging
from datetime import datetime
from typing import List, Optional

import redis
from rq import Queue
from rq.job import Job
from rq import Retry

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
PROCESSED_EVENTS_ZSET = "eonet:metrics:processed"
DLQ_PREFIX = "eonet:dlq:"
DLQ_INDEX_KEY = "eonet:dlq:index"
INFERENCE_WRITE_PREFIX = "eonet:inference-write:"


# ── Seen-event deduplication ─────────────────────────────────────────────────

async def get_seen_event_ids() -> set:
    """Return the set of event IDs already enqueued/processed."""
    try:
        members = redis_conn.smembers(SEEN_EVENTS_KEY)
        return {m.decode() for m in members}
    except Exception as e:
        logger.error(f"Failed to read seen events: {e}")
        return set()


async def mark_event_seen(event_id: str) -> bool:
    """Atomically mark an event ID as seen. Returns True only if newly added."""
    try:
        added = redis_conn.sadd(SEEN_EVENTS_KEY, event_id)
        redis_conn.expire(SEEN_EVENTS_KEY, 60 * 60 * 24 * 7)  # 7-day TTL
        return bool(added)
    except Exception as e:
        logger.error(f"Failed to mark event seen: {e}")
        return False


# ── Event enqueuing ──────────────────────────────────────────────────────────

async def enqueue_event(event: EONETEvent) -> str:
    """Enqueue an EONET event for AI inference. Returns the RQ job ID."""
    from app.queue.worker_tasks import process_event_task  # avoid circular import

    job = inference_queue.enqueue(
        process_event_task,
        event.model_dump(),
        job_timeout=120,
        retry=Retry(max=settings.job_max_retries, interval=[5, 20]),
        result_ttl=ENRICHED_EVENT_TTL,
        failure_ttl=ENRICHED_EVENT_TTL,
        on_failure=process_event_dead_letter,
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


def try_idempotent_inference_write(event_id: str, data: dict, write_key: str) -> bool:
    """
    Perform a write-once inference result update.
    Returns True when write succeeds, False if key already consumed.
    """
    marker_key = f"{INFERENCE_WRITE_PREFIX}{event_id}:{write_key}"
    try:
        added = redis_conn.set(marker_key, "1", nx=True, ex=ENRICHED_EVENT_TTL)
        if not added:
            return False
        update_enriched_event(event_id, data)
        return True
    except Exception as e:
        logger.error(f"Failed idempotent write for event {event_id}: {e}")
        return False


def get_all_enriched_events() -> List[dict]:
    """Return all enriched event records, sorted newest-first."""
    events: List[dict] = []
    for key in redis_conn.scan_iter(match=f"{ENRICHED_EVENT_PREFIX}*"):
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
        now_ts = datetime.utcnow().timestamp()
        one_min_ago = now_ts - 60
        ten_min_ago = now_ts - 600

        # Keep only recent metrics to bound memory.
        redis_conn.zremrangebyscore(PROCESSED_EVENTS_ZSET, 0, ten_min_ago)
        processed_last_min = redis_conn.zcount(PROCESSED_EVENTS_ZSET, one_min_ago, now_ts)

        workers = Worker.all(connection=redis_conn)
        return QueueStats(
            queued=inference_queue.count,
            started=inference_queue.started_job_registry.count,
            finished=inference_queue.finished_job_registry.count,
            failed=inference_queue.failed_job_registry.count,
            workers=len(workers),
            events_per_minute=float(processed_last_min),
        )
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        return QueueStats(queued=0, started=0, finished=0, failed=0, workers=0, events_per_minute=0.0)


def record_processed_event(event_id: str, processed_at: Optional[datetime] = None) -> None:
    """Track successfully processed events for throughput metrics."""
    ts = (processed_at or datetime.utcnow()).timestamp()
    member = f"{event_id}:{ts}"
    try:
        redis_conn.zadd(PROCESSED_EVENTS_ZSET, {member: ts})
    except Exception as e:
        logger.error(f"Failed to record processed event metric for {event_id}: {e}")


def save_dead_letter(job_id: str, payload: dict) -> None:
    """Persist dead-letter metadata for jobs that exhausted retries."""
    key = f"{DLQ_PREFIX}{job_id}"
    try:
        redis_conn.setex(key, ENRICHED_EVENT_TTL, json.dumps(payload, default=str))
        redis_conn.lpush(DLQ_INDEX_KEY, key)
        redis_conn.ltrim(DLQ_INDEX_KEY, 0, 499)
        redis_conn.expire(DLQ_INDEX_KEY, ENRICHED_EVENT_TTL)
    except Exception as e:
        logger.error(f"Failed to save dead-letter payload for job {job_id}: {e}")


def list_dead_letters(limit: int = 50) -> List[dict]:
    """Return newest dead-letter entries."""
    keys = redis_conn.lrange(DLQ_INDEX_KEY, 0, max(0, limit - 1))
    payloads: List[dict] = []
    for key in keys:
        raw = redis_conn.get(key)
        if not raw:
            continue
        try:
            payloads.append(json.loads(raw))
        except Exception:
            continue
    return payloads
