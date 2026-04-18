from fastapi import APIRouter
import redis as redis_lib

from app.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Liveness probe")
async def health():
    return {"status": "ok", "service": "nasa-eonet-inference-api"}


@router.get("/ready", summary="Readiness probe — checks Redis connectivity")
async def ready():
    try:
        r = redis_lib.from_url(settings.redis_url)
        r.ping()
        return {"status": "ready", "redis": "connected"}
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "redis": str(e)},
        )
