"""WebSocket router with connection manager for real-time push to the dashboard."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    """Manages a set of active WebSocket connections and broadcasts messages."""

    def __init__(self, name: str = ""):
        self.name = name
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.debug(f"[WS:{self.name}] client connected (total={len(self._connections)})")

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.debug(f"[WS:{self.name}] client disconnected (total={len(self._connections)})")

    async def broadcast(self, message: dict) -> None:
        """Send JSON message to all connected clients; silently drop dead connections."""
        if not self._connections:
            return
        dead: set[WebSocket] = set()
        for ws in self._connections.copy():
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections.discard(ws)

    def __len__(self) -> int:
        return len(self._connections)


# Shared connection managers — imported by main.py background tasks
events_manager = ConnectionManager("events")
queue_manager_ws = ConnectionManager("queue")


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    """Stream completed EnrichedEvent payloads as they finish inference."""
    await events_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()   # keep-alive ping from client
    except WebSocketDisconnect:
        events_manager.disconnect(websocket)


@router.websocket("/ws/queue")
async def ws_queue(websocket: WebSocket):
    """Stream queue stats every few seconds."""
    await queue_manager_ws.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        queue_manager_ws.disconnect(websocket)
