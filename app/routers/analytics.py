from fastapi import APIRouter, Query
from collections import defaultdict

from app.queue.manager import get_all_enriched_events

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


def _is_simulated_event(enriched_event: dict) -> bool:
    event_id = ((enriched_event.get("event") or {}).get("id") or "")
    return event_id.startswith(("SIM_", "SPIKE_"))


def _filter_events(events: list[dict], include_simulated: bool) -> list[dict]:
    if include_simulated:
        return events
    return [e for e in events if not _is_simulated_event(e)]


@router.get("/summary", summary="Aggregated event counts, average severity, and risk distribution")
async def summary(include_simulated: bool = Query(False, description="Include synthetic load/spike events")):
    events = _filter_events(get_all_enriched_events(), include_simulated)
    category_counts: dict = defaultdict(int)
    risk_counts: dict = defaultdict(int)
    severity_scores: list = []
    inference_modes: dict = defaultdict(int)
    trend_counts: dict = defaultdict(int)

    for e in events:
        cats = e.get("event", {}).get("categories", [])
        if cats:
            category_counts[cats[0].get("title", "Unknown")] += 1

        inf = e.get("inference") or {}
        if inf:
            risk_counts[inf.get("risk_level", "UNKNOWN")] += 1
            if inf.get("severity_score") is not None:
                severity_scores.append(float(inf["severity_score"]))
            inference_modes[inf.get("inference_mode", "heuristic")] += 1
            trend_counts[inf.get("trend", "STABLE")] += 1

    avg_severity = round(sum(severity_scores) / len(severity_scores), 1) if severity_scores else 0.0

    return {
        "total_events": len(events),
        "by_category": dict(category_counts),
        "by_risk_level": dict(risk_counts),
        "by_trend": dict(trend_counts),
        "average_severity": avg_severity,
        "inference_modes": dict(inference_modes),
    }


@router.get("/hotspots", summary="Top 10 highest-severity events by location")
async def hotspots(include_simulated: bool = Query(False, description="Include synthetic load/spike events")):
    events = _filter_events(get_all_enriched_events(), include_simulated)
    spots = []

    for e in events:
        inf = e.get("inference") or {}
        if not inf or (inf.get("severity_score") or 0) < 50:
            continue
        geoms = e.get("event", {}).get("geometry", [])
        if not geoms:
            continue
        latest = geoms[-1]
        coords = latest.get("coordinates", [])
        if len(coords) >= 2:
            spots.append({
                "title": e.get("event", {}).get("title", "Unknown"),
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "severity_score": inf.get("severity_score"),
                "risk_level": inf.get("risk_level"),
                "category": inf.get("category"),
                "trend": inf.get("trend"),
            })

    spots.sort(key=lambda x: x["severity_score"], reverse=True)
    return {"hotspots": spots[:10]}
