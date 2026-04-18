"""Background coroutine that polls NASA EONET and enqueues new events."""

import asyncio
import logging
from datetime import datetime

from app.eonet.client import fetch_open_events
from app.queue.manager import enqueue_event, mark_event_seen, unmark_event_seen
from app.config import settings

logger = logging.getLogger(__name__)

# Shared state — read by the queue stats broadcaster
poller_status: dict = {
    "last_poll_at": None,
    "next_poll_in": settings.poll_interval_seconds,
    "events_found": 0,
    "events_new": 0,
    "is_polling": False,
}


async def run_poller(broadcast_fn=None) -> None:
    """
    Continuously poll NASA EONET for new natural events.
    Deduplicates using a Redis Set so only genuinely new events are enqueued.
    Optionally broadcasts poller status via a callable (WebSocket broadcast).
    """
    logger.info(
        f"🛰️  EONET Poller started — interval={settings.poll_interval_seconds}s, "
        f"days_window={settings.event_days_window}, max={settings.max_events_per_poll}"
    )

    while True:
        poller_status["is_polling"] = True

        try:
            events = await fetch_open_events(
                days=settings.event_days_window,
                limit=settings.max_events_per_poll,
                status="open",
            )
            new_count = 0

            for event in events:
                is_new = await mark_event_seen(event.id)
                if is_new:
                    job_id = await enqueue_event(event)
                    if job_id:
                        new_count += 1
                        logger.info(f"  ↳ Enqueued: [{event.id}] {event.title}")
                    else:
                        # Queue is full; allow this event to be retried on next poll.
                        await unmark_event_seen(event.id)
                        logger.warning(f"  ↳ Deferred (queue full): [{event.id}] {event.title}")

            poller_status.update({
                "last_poll_at": datetime.utcnow().isoformat() + "Z",
                "events_found": len(events),
                "events_new": new_count,
                "is_polling": False,
            })

            if broadcast_fn and new_count > 0:
                await broadcast_fn({"type": "poll_complete", "data": {**poller_status}})

            logger.info(
                f"Poll complete — {len(events)} events fetched, {new_count} new enqueued"
            )

        except Exception as e:
            logger.error(f"Poller error: {type(e).__name__}: {e}")
            poller_status["is_polling"] = False

        # Countdown to next poll — updates next_poll_in every second
        for remaining in range(settings.poll_interval_seconds, 0, -1):
            poller_status["next_poll_in"] = remaining
            await asyncio.sleep(1)
