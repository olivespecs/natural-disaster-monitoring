"""
NASA EONET Real-Time AI Inference System
FastAPI application entry point.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.eonet.poller import run_poller, poller_status
from app.queue.manager import redis_conn, ENRICHED_EVENT_PREFIX, get_queue_stats
from app.routers import health, events, queue_router, analytics, websocket_router
from app.routers.websocket_router import events_manager, queue_manager_ws

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Background tasks ─────────────────────────────────────────────────────────

_broadcasted_completed_at: dict[str, str] = {}


async def event_watcher() -> None:
    """
    Poll Redis every 2s for completed inference events and
    broadcast each completion once to all connected WebSocket clients.
    """
    global _broadcasted_completed_at
    while True:
        try:
            for raw_key in redis_conn.scan_iter(match=f"{ENRICHED_EVENT_PREFIX}*"):
                key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
                raw = redis_conn.get(key)
                if raw:
                    data = json.loads(raw)
                    if data.get("status") == "completed":
                        event = data.get("event") or {}
                        event_id = event.get("id")
                        completed_at = str(data.get("completed_at") or "")
                        if not event_id:
                            continue
                        if _broadcasted_completed_at.get(event_id) == completed_at:
                            continue
                        _broadcasted_completed_at[event_id] = completed_at
                        await events_manager.broadcast(
                            {"type": "event_completed", "data": data}
                        )
        except Exception as e:
            logger.error(f"Event watcher error: {e}")

        await asyncio.sleep(2)


async def queue_stats_broadcaster() -> None:
    """Broadcast live queue stats + poller status to all queue WebSocket clients every 3s."""
    while True:
        try:
            stats = get_queue_stats()
            payload = {**stats.model_dump(), **poller_status}
            await queue_manager_ws.broadcast({"type": "queue_stats", "data": payload})
        except Exception as e:
            logger.error(f"Stats broadcaster error: {e}")
        await asyncio.sleep(3)


# ── App lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting NASA EONET AI Inference System...")
    gemini_status = "✓ enabled" if settings.gemini_api_key else "✗ not set (heuristic fallback active)"
    logger.info(f"   Gemini API key: {gemini_status}")
    logger.info(f"   Redis: {settings.redis_url}")
    logger.info(f"   Poll interval: {settings.poll_interval_seconds}s")

    tasks = [
        asyncio.create_task(run_poller(events_manager.broadcast), name="eonet-poller"),
        asyncio.create_task(event_watcher(), name="event-watcher"),
        asyncio.create_task(queue_stats_broadcaster(), name="stats-broadcaster"),
    ]

    yield

    logger.info("Shutting down background tasks...")
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="NASA EONET Real-Time AI Inference System",
    description=(
        "Real-time natural event monitoring powered by NASA EONET data, "
        "with AI-driven risk analysis using Gemini API (with heuristic fallback)."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Routers
app.include_router(health.router)
app.include_router(events.router)
app.include_router(queue_router.router)
app.include_router(analytics.router)
app.include_router(websocket_router.router)

# Static files (dashboard)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
async def serve_dashboard():
    return FileResponse("app/static/index.html")
