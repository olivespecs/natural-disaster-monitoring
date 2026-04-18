from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from app.queue.manager import get_all_enriched_events, get_enriched_event

router = APIRouter(prefix="/api/v1", tags=["Events"])


@router.get("/events", summary="List enriched events with optional filters")
async def list_events(
    category: Optional[str] = Query(None, description="Filter by EONET category ID, e.g. wildfires"),
    risk_level: Optional[str] = Query(None, description="Filter by risk level: LOW, MEDIUM, HIGH, CRITICAL"),
    status: Optional[str] = Query(None, description="Filter by job status: queued, processing, completed, failed"),
    limit: int = Query(default=100, le=500),
):
    events = get_all_enriched_events()

    if category:
        events = [
            e for e in events
            if any(c.get("id") == category for c in e.get("event", {}).get("categories", []))
        ]
    if risk_level:
        rl = risk_level.upper()
        events = [
            e for e in events
            if (e.get("inference") or {}).get("risk_level") == rl
        ]
    if status:
        events = [e for e in events if e.get("status") == status]

    return {"events": events[:limit], "total": len(events)}


@router.get("/events/geojson", summary="GeoJSON FeatureCollection for Leaflet.js map")
async def events_geojson(
    category: Optional[str] = None,
    risk_level: Optional[str] = None,
):
    events = get_all_enriched_events()
    features = []

    if category:
        events = [
            e for e in events
            if any(c.get("id") == category for c in e.get("event", {}).get("categories", []))
        ]
    if risk_level:
        rl = risk_level.upper()
        events = [
            e for e in events
            if (e.get("inference") or {}).get("risk_level") == rl
        ]

    for e in events:
        event_data = e.get("event", {})
        inference = e.get("inference") or {}
        geometries = event_data.get("geometry", [])

        if not geometries:
            continue

        # Use the most recent geometry point
        latest = geometries[-1]
        coords = latest.get("coordinates")
        if not coords or not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue

        cats = event_data.get("categories", [])
        category_id = cats[0].get("id", "") if cats else ""
        category_title = inference.get("category") or (cats[0].get("title", "Unknown") if cats else "Unknown")

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(coords[0]), float(coords[1])],
            },
            "properties": {
                "id": event_data.get("id"),
                "title": event_data.get("title"),
                "category": category_title,
                "category_id": category_id,
                "severity_score": inference.get("severity_score", 0),
                "risk_level": inference.get("risk_level", "MEDIUM"),
                "trend": inference.get("trend", "STABLE"),
                "estimated_impact": inference.get("estimated_impact", ""),
                "impact_narrative": inference.get("impact_narrative", ""),
                "recommendations": inference.get("recommendations", []),
                "inference_mode": inference.get("inference_mode", "heuristic"),
                "confidence": inference.get("confidence", 0),
                "status": e.get("status"),
                "date": latest.get("date"),
                "link": event_data.get("link", ""),
            },
        })

    return {"type": "FeatureCollection", "features": features}


@router.get("/events/{event_id}", summary="Get a single enriched event by ID")
async def get_event(event_id: str):
    event = get_enriched_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found")
    return event
