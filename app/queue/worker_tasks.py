"""RQ worker task functions — these run inside the worker process."""

import json
import logging
from datetime import datetime

from app.models import EONETEvent
from app.inference.engine import run_inference

logger = logging.getLogger(__name__)


def process_event_task(event_dict: dict) -> dict:
    """
    RQ task: deserialize an EONET event, run AI inference, and persist results.
    Called by the RQ worker process.
    """
    from app.queue.manager import get_enriched_event, update_enriched_event

    event = EONETEvent(**event_dict)
    event_id = event.id

    # Mark as processing
    enriched = get_enriched_event(event_id) or {
        "event": event_dict,
        "job_id": "unknown",
        "status": "processing",
        "queued_at": datetime.utcnow().isoformat(),
    }
    enriched["status"] = "processing"
    update_enriched_event(event_id, enriched)

    try:
        result = run_inference(event)

        enriched["inference"] = json.loads(result.model_dump_json())
        enriched["status"] = "completed"
        enriched["completed_at"] = datetime.utcnow().isoformat()
        update_enriched_event(event_id, enriched)

        logger.info(
            f"✓ [{event_id}] {result.category} — "
            f"risk={result.risk_level} score={result.severity_score} "
            f"mode={result.inference_mode}"
        )
        return json.loads(result.model_dump_json())

    except Exception as e:
        logger.error(f"✗ [{event_id}] Inference failed: {e}")
        enriched["status"] = "failed"
        enriched["error"] = str(e)
        update_enriched_event(event_id, enriched)
        raise
