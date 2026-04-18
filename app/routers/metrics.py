from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.metrics.prometheus import register_metrics_collector

router = APIRouter(tags=["Metrics"])

register_metrics_collector()


@router.get("/metrics", include_in_schema=False, summary="Prometheus metrics")
def metrics_endpoint():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
