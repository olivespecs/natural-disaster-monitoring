"""RQ worker task functions — these run inside the worker process."""

import json
import logging
import subprocess
import time
from datetime import datetime
from typing import Any, List

from app.models import EONETEvent
from app.inference.engine import run_inference

logger = logging.getLogger(__name__)


def _read_gpu_utilization_percent() -> float:
    """Best-effort GPU utilization read; returns 0 when unavailable."""
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        if completed.returncode != 0:
            return 0.0
        first = (completed.stdout or "").strip().splitlines()[0]
        return float(first)
    except Exception:
        return 0.0


def _process_single_event(event_dict: dict[str, Any]) -> dict[str, Any]:
    """Run one event through inference and persist status updates."""
    from app.queue.manager import (
        get_enriched_event,
        update_enriched_event,
        record_processed_event,
        try_idempotent_inference_write,
        redis_conn,
        update_gpu_utilization,
    )

    event = EONETEvent(**event_dict)
    event_id = event.id
    started = time.perf_counter()

    enriched = get_enriched_event(event_id) or {
        "event": event_dict,
        "job_id": "unknown",
        "status": "processing",
        "queued_at": datetime.utcnow().isoformat(),
    }
    if enriched.get("status") == "completed" and enriched.get("inference"):
        logger.info(f"event_already_completed event_id={event_id} job_id={enriched.get('job_id')}")
        return enriched["inference"]

    try:
        redis_conn.setex("eonet:worker:current_task", 300, event_id)
    except Exception as e:
        logger.warning(f"Failed to track current task: {e}")

    enriched["status"] = "processing"
    enriched["attempts"] = int(enriched.get("attempts") or 0) + 1
    update_enriched_event(event_id, enriched)

    try:
        result = run_inference(event)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        enriched["inference"] = json.loads(result.model_dump_json())
        enriched["status"] = "completed"
        enriched["completed_at"] = datetime.utcnow().isoformat()
        write_key = enriched.get("job_id") or f"{event_id}:{enriched['completed_at']}"
        enriched["inference_write_key"] = write_key
        wrote = try_idempotent_inference_write(event_id, enriched, write_key)
        if wrote:
            record_processed_event(event_id, elapsed_ms)
            update_gpu_utilization(_read_gpu_utilization_percent())
        else:
            logger.warning(
                f"idempotent_write_skipped event_id={event_id} job_id={enriched.get('job_id')} "
                f"inference_mode={result.inference_mode} latency_ms={elapsed_ms}"
            )

        logger.info(
            f"event_processed event_id={event_id} job_id={enriched.get('job_id')} "
            f"inference_mode={result.inference_mode} latency_ms={elapsed_ms} "
            f"risk={result.risk_level} score={result.severity_score}"
        )
        return json.loads(result.model_dump_json())

    except Exception as e:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error(
            f"event_processing_failed event_id={event_id} job_id={enriched.get('job_id')} "
            f"inference_mode=unknown latency_ms={elapsed_ms} error={type(e).__name__}:{e}"
        )
        enriched["status"] = "failed"
        enriched["error"] = str(e)
        enriched["failed_at"] = datetime.utcnow().isoformat()
        update_enriched_event(event_id, enriched)
        raise
    finally:
        try:
            redis_conn.delete("eonet:worker:current_task")
        except Exception:
            pass


def process_event_task(event_dict: dict) -> dict:
    """
    RQ task: deserialize an EONET event, run AI inference, and persist results.
    Called by the RQ worker process. Tracks current event ID in Redis for telemetry.
    """
    return _process_single_event(event_dict)


def process_event_batch_task(events_payload: List[dict[str, Any]]) -> dict[str, Any]:
    """
    RQ task: process a batch of EONET events in one worker invocation.
    Individual event failures are isolated so one bad item does not drop the whole batch.
    """
    results: List[dict[str, Any]] = []
    failures: List[dict[str, str]] = []

    for event_dict in events_payload:
        event_id = str(event_dict.get("id", "unknown"))
        try:
            result = _process_single_event(event_dict)
            results.append(result)
        except Exception as e:
            failures.append({"event_id": event_id, "error": f"{type(e).__name__}: {e}"})

    logger.info(
        "batch_processed size=%s success=%s failures=%s",
        len(events_payload),
        len(results),
        len(failures),
    )
    return {"processed": len(results), "failed": len(failures), "failures": failures}


def process_event_dead_letter(job, _connection, exc_type, exc_value, _traceback) -> None:
    """RQ failure callback: move exhausted jobs into a dead-letter list."""
    from app.queue.manager import save_dead_letter, get_enriched_event, update_enriched_event

    retries_left = getattr(job, "retries_left", None)
    if retries_left and retries_left > 0:
        return

    event_id = "unknown"
    if job.args and isinstance(job.args[0], dict):
        event_id = job.args[0].get("id", "unknown")

    payload = {
        "job_id": job.id,
        "event_id": event_id,
        "failed_at": datetime.utcnow().isoformat(),
        "error_type": getattr(exc_type, "__name__", str(exc_type)),
        "error_message": str(exc_value),
        "retries_left": retries_left,
    }
    save_dead_letter(job.id, payload)

    enriched = get_enriched_event(event_id)
    if enriched:
        enriched["status"] = "dead_letter"
        enriched["dead_letter"] = payload
        update_enriched_event(event_id, enriched)

    logger.error(
        f"event_dead_lettered event_id={event_id} job_id={job.id} "
        f"inference_mode=unknown latency_ms=0 error={payload['error_type']}:{payload['error_message']}"
    )
