"""
Main AI inference engine.

Two-tier execution:
  1. Heuristic pre-scoring  — always runs (fast, deterministic, structured)
  2. Gemini enrichment      — runs if GEMINI_API_KEY is set; falls back to heuristic on any error
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Optional

from app.models import EONETEvent, InferenceResult
from app.inference.rules import (
    BASE_SEVERITY,
    CATEGORY_MAP,
    geometry_bonus,
    severity_to_risk,
    severity_to_trend,
    get_recommendations,
)
from app.inference.geo_utils import extract_centroid, estimate_impact_description, compute_area_proxy
from app.inference.gemini_analyzer import GeminiAnalyzer, GeminiUnavailable
from app.config import settings

logger = logging.getLogger(__name__)

# Worker-process singleton — initialized once, reused for every task
_gemini: Optional[GeminiAnalyzer] = None
_gemini_attempted = False          # avoid repeated init failures every call


def _build_heuristic_state(event: EONETEvent) -> dict[str, Any]:
    """Build deterministic baseline inference values used by both single and batch paths."""
    category_id = event.categories[0].id if event.categories else "default"
    category_title = CATEGORY_MAP.get(category_id, event.categories[0].title if event.categories else "Unknown")

    base = float(BASE_SEVERITY.get(category_id, 45))
    geo_count = len(event.geometry)
    severity_score = min(100.0, base + geometry_bonus(geo_count))

    geom_dicts = [g.model_dump() for g in event.geometry]
    lat, lon = extract_centroid(geom_dicts)
    area = compute_area_proxy(geom_dicts)
    if area > 10:
        severity_score = min(100.0, severity_score + 10.0)

    risk_level = severity_to_risk(severity_score)
    trend = severity_to_trend(severity_score, geo_count)
    estimated_impact = estimate_impact_description(lat or 30.0, lon or 0.0, risk_level)
    recommendations = get_recommendations(category_id, risk_level)

    location_str = f"{lat:.1f}°, {lon:.1f}°" if (lat is not None and lon is not None) else "an undisclosed location"
    impact_narrative = (
        f"A {category_title.lower()} event — '{event.title}' — has been detected at {location_str}, "
        f"with {geo_count} tracking data points suggesting {'prolonged or widening activity' if geo_count > 10 else 'recent onset'}. "
        f"Classified as {risk_level} risk (severity {severity_score:.0f}/100), "
        f"this event warrants {'immediate emergency response' if risk_level in ('CRITICAL', 'HIGH') else 'continued monitoring and standard preparedness measures'}."
    )

    confidence = 0.65
    if lat is not None:
        confidence += 0.08
    if geo_count > 5:
        confidence += 0.07
    if geo_count > 20:
        confidence += 0.05

    return {
        "category_title": category_title,
        "severity_score": severity_score,
        "risk_level": risk_level,
        "trend": trend,
        "estimated_impact": estimated_impact,
        "impact_narrative": impact_narrative,
        "recommendations": recommendations,
        "inference_mode": "heuristic",
        "pipeline_path": "TIER_1_HEURISTIC",
        "confidence": confidence,
        "lat": lat,
        "lon": lon,
    }


def _to_inference_result(event: EONETEvent, state: dict[str, Any]) -> InferenceResult:
    """Convert mutable inference state into the output model."""
    return InferenceResult(
        event_id=event.id,
        category=state["category_title"],
        severity_score=round(float(state["severity_score"]), 1),
        risk_level=state["risk_level"],
        trend=state["trend"],
        estimated_impact=state["estimated_impact"],
        impact_narrative=state["impact_narrative"],
        recommendations=state["recommendations"],
        inference_mode=state["inference_mode"],
        pipeline_path=state["pipeline_path"],
        confidence=round(float(state["confidence"]), 2),
        processed_at=datetime.utcnow(),
    )


def _get_gemini() -> Optional[GeminiAnalyzer]:
    global _gemini, _gemini_attempted
    if _gemini_attempted:
        return _gemini
    _gemini_attempted = True

    if not settings.gemini_api_key:
        logger.info("No GEMINI_API_KEY — inference will use heuristic engine")
        return None

    try:
        _gemini = GeminiAnalyzer()
        logger.info("Gemini analyzer ready ✓")
    except Exception as e:
        logger.warning(f"Gemini init failed, falling back to heuristic: {e}")
        _gemini = None

    return _gemini


def run_inference(event: EONETEvent) -> InferenceResult:
    """
    Run full AI inference pipeline on a single EONET event.

    Pipeline:
      Step 1 — Heuristic pre-scoring (always)
      Step 2 — Gemini enrichment (if available, auto-fallback on failure)
    """
    state = _build_heuristic_state(event)

    # ── Step 2: Gemini enrichment ─────────────────────────────────────────────
    gemini = _get_gemini()
    if gemini:
        try:
            result = gemini.analyze(
                event,
                state["severity_score"],
                state["risk_level"],
                state["lat"],
                state["lon"],
            )
            state["impact_narrative"] = result["impact_narrative"]
            state["recommendations"] = result["recommendations"]
            state["trend"] = result["trend"]
            state["inference_mode"] = settings.gemini_model
            state["pipeline_path"] = "TIER_2_GEMINI"
            state["confidence"] = min(0.97, float(state["confidence"]) + 0.20)
            logger.info(
                f"gemini_analysis_complete event_id={event.id} "
                f"inference_mode={state['inference_mode']} trend={state['trend']}"
            )
        except GeminiUnavailable as e:
            logger.warning(
                f"gemini_unavailable_fallback event_id={event.id} "
                f"inference_mode=heuristic reason={e}"
            )

    return _to_inference_result(event, state)


def run_inference_batch(events: list[EONETEvent]) -> list[InferenceResult]:
    """
    Run inference for a batch of events in one call.

    Uses per-event heuristic pre-scoring and parallel Gemini enrichment across the batch,
    while preserving input order and per-event fallback behavior.
    """
    if not events:
        return []

    states = [_build_heuristic_state(event) for event in events]
    gemini = _get_gemini()
    if not gemini:
        return [_to_inference_result(event, state) for event, state in zip(events, states)]

    max_workers = min(4, len(events))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for idx, event in enumerate(events):
            state = states[idx]
            futures[executor.submit(
                gemini.analyze,
                event,
                state["severity_score"],
                state["risk_level"],
                state["lat"],
                state["lon"],
            )] = idx

        for future in as_completed(futures):
            idx = futures[future]
            event = events[idx]
            state = states[idx]
            try:
                result = future.result()
                state["impact_narrative"] = result["impact_narrative"]
                state["recommendations"] = result["recommendations"]
                state["trend"] = result["trend"]
                state["inference_mode"] = settings.gemini_model
                state["pipeline_path"] = "TIER_2_GEMINI"
                state["confidence"] = min(0.97, float(state["confidence"]) + 0.20)
            except GeminiUnavailable as e:
                logger.warning(
                    f"gemini_unavailable_fallback event_id={event.id} "
                    f"inference_mode=heuristic reason={e}"
                )
            except Exception as e:
                logger.warning(
                    f"gemini_batch_error_fallback event_id={event.id} "
                    f"inference_mode=heuristic reason={type(e).__name__}:{e}"
                )

    return [_to_inference_result(event, state) for event, state in zip(events, states)]
