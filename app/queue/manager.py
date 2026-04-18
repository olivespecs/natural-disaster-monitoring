"""Queue management layer — thin wrapper over Redis + RQ."""

import json
import logging
from datetime import datetime
from typing import List, Optional

import redis
from rq import Queue
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
LATENCY_LIST_KEY = "eonet:metrics:latency"
DLQ_PREFIX = "eonet:dlq:"
DLQ_INDEX_KEY = "eonet:dlq:index"
INFERENCE_WRITE_PREFIX = "eonet:inference-write:"
METRICS_EVENTS_PROCESSED_TOTAL_KEY = "eonet:metrics:events_processed_total"
METRICS_INFERENCE_LATENCY_SUM_SECONDS_KEY = "eonet:metrics:latency_sum_seconds"
METRICS_INFERENCE_LATENCY_COUNT_KEY = "eonet:metrics:latency_count"
METRICS_INFERENCE_LATENCY_BUCKET_PREFIX = "eonet:metrics:latency_bucket:"
METRICS_GPU_UTILIZATION_KEY = "eonet:metrics:gpu_utilization"

LATENCY_BUCKET_BOUNDS_SECONDS = [0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]


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


async def unmark_event_seen(event_id: str) -> None:
    """Remove an event ID from the seen set (used when enqueue is deferred)."""
    try:
        redis_conn.srem(SEEN_EVENTS_KEY, event_id)
    except Exception as e:
        logger.error(f"Failed to unmark event seen: {e}")


# ── Event enqueuing ──────────────────────────────────────────────────────────

def _queue_has_capacity(extra_jobs: int = 1) -> bool:
    """Return True when queue depth is below configured cap."""
    return (inference_queue.count + extra_jobs) <= settings.max_queue_depth


def _store_initial_enriched_event(event: EONETEvent, job_id: str) -> None:
    """Store initial Redis status for a queued event."""
    initial = {
        "event": event.model_dump(),
        "inference": None,
        "job_id": job_id,
        "status": "queued",
        "queued_at": datetime.utcnow().isoformat(),
        "completed_at": None,
    }
    redis_conn.setex(
        f"{ENRICHED_EVENT_PREFIX}{event.id}",
        ENRICHED_EVENT_TTL,
        json.dumps(initial, default=str),
    )


async def enqueue_event(event: EONETEvent, at_front: bool = False) -> Optional[str]:
    """Enqueue one EONET event for inference. Returns job ID, or None if queue is full."""
    from app.queue.worker_tasks import process_event_task, process_event_dead_letter  # avoid circular import

    if not _queue_has_capacity(1):
        logger.warning(
            f"Queue depth cap reached ({settings.max_queue_depth}); skipping event enqueue {event.id}"
        )
        return None

    job = inference_queue.enqueue(
        process_event_task,
        event.model_dump(),
        job_timeout=120,
        retry=Retry(max=settings.job_max_retries, interval=[5, 20]),
        result_ttl=ENRICHED_EVENT_TTL,
        failure_ttl=ENRICHED_EVENT_TTL,
        on_failure=process_event_dead_letter,
        at_front=at_front,
    )

    _store_initial_enriched_event(event, job.id)
    logger.debug(f"Enqueued event {event.id} → job {job.id}")
    return job.id


async def enqueue_event_batch(events: List[EONETEvent], at_front: bool = False) -> Optional[str]:
    """
    Enqueue a batch of EONET events for inference.
    Returns one RQ job ID for the whole batch, or None if queue is full.
    """
    if not events:
        return None

    from app.queue.worker_tasks import process_event_batch_task, process_event_dead_letter  # avoid circular import

    if not _queue_has_capacity(1):
        logger.warning(
            f"Queue depth cap reached ({settings.max_queue_depth}); deferring batch of {len(events)} events"
        )
        return None

    payload = [event.model_dump() for event in events]
    job = inference_queue.enqueue(
        process_event_batch_task,
        payload,
        job_timeout=max(120, 45 * len(events)),
        retry=Retry(max=settings.job_max_retries, interval=[5, 20]),
        result_ttl=ENRICHED_EVENT_TTL,
        failure_ttl=ENRICHED_EVENT_TTL,
        on_failure=process_event_dead_letter,
        at_front=at_front,
    )

    for event in events:
        _store_initial_enriched_event(event, job.id)

    logger.debug(f"Enqueued batch of {len(events)} events → job {job.id}")
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
    """Return live queue depth, worker stats, latency, and backpressure warning."""
    try:
        from rq import Worker
        now_ts = datetime.utcnow().timestamp()
        one_min_ago = now_ts - 60
        ten_min_ago = now_ts - 600

        # Keep only recent metrics to bound memory.
        redis_conn.zremrangebyscore(PROCESSED_EVENTS_ZSET, 0, ten_min_ago)
        processed_last_min = redis_conn.zcount(PROCESSED_EVENTS_ZSET, one_min_ago, now_ts)

        latencies_raw = redis_conn.lrange(LATENCY_LIST_KEY, 0, 99)
        latencies = [int(x) for x in latencies_raw if x.decode('utf-8').isdigit()] if latencies_raw else []
        last_latency = latencies[0] if latencies else 0
        avg_latency = float(sum(latencies)) / len(latencies) if latencies else 0.0

        workers = Worker.all(connection=redis_conn)
        
        # Get current processing event ID from Redis
        current_event_id = None
        try:
            val = redis_conn.get("eonet:worker:current_task")
            current_event_id = val.decode() if val else None
        except Exception:
            pass
        
        # Backpressure warning: True if queue depth > 10
        queue_depth = inference_queue.count
        backpressure = queue_depth > 10
        
        return QueueStats(
            queued=queue_depth,
            started=inference_queue.started_job_registry.count,
            finished=inference_queue.finished_job_registry.count,
            failed=inference_queue.failed_job_registry.count,
            workers=len(workers),
            events_per_minute=float(processed_last_min),
            avg_latency_ms=round(avg_latency, 2),
            last_latency_ms=last_latency,
            backpressure_warning=backpressure,
            current_processing_event_id=current_event_id
        )
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        return QueueStats(queued=0, started=0, finished=0, failed=0, workers=0, events_per_minute=0.0, avg_latency_ms=0.0, last_latency_ms=0, backpressure_warning=False, current_processing_event_id=None)


def record_processed_event(event_id: str, elapsed_ms: Optional[int] = None, processed_at: Optional[datetime] = None) -> None:
    """Track successfully processed events for throughput metrics."""
    ts = (processed_at or datetime.utcnow()).timestamp()
    member = f"{event_id}:{ts}"
    try:
        redis_conn.zadd(PROCESSED_EVENTS_ZSET, {member: ts})
        redis_conn.incr(METRICS_EVENTS_PROCESSED_TOTAL_KEY)
        if elapsed_ms is not None:
            redis_conn.lpush(LATENCY_LIST_KEY, str(elapsed_ms))
            redis_conn.ltrim(LATENCY_LIST_KEY, 0, 99)
            elapsed_seconds = max(0.0, float(elapsed_ms) / 1000.0)
            redis_conn.incr(METRICS_INFERENCE_LATENCY_COUNT_KEY)
            redis_conn.incrbyfloat(METRICS_INFERENCE_LATENCY_SUM_SECONDS_KEY, elapsed_seconds)

            bucket_label = "+Inf"
            for bound in LATENCY_BUCKET_BOUNDS_SECONDS:
                if elapsed_seconds <= bound:
                    bucket_label = str(bound)
                    break
            redis_conn.incr(f"{METRICS_INFERENCE_LATENCY_BUCKET_PREFIX}{bucket_label}")
    except Exception as e:
        logger.error(f"Failed to record processed event metric for {event_id}: {e}")


def update_gpu_utilization(value: float) -> None:
    """Persist latest GPU utilization in Redis for /metrics scraping."""
    clamped = min(100.0, max(0.0, float(value)))
    try:
        redis_conn.set(METRICS_GPU_UTILIZATION_KEY, f"{clamped:.2f}")
    except Exception as e:
        logger.error(f"Failed to update GPU utilization metric: {e}")


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
