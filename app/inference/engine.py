"""
Main AI inference engine.

Two-tier execution:
  1. Heuristic pre-scoring  — always runs (fast, deterministic, structured)
  2. Gemini enrichment      — runs if GEMINI_API_KEY is set; falls back to heuristic on any error
"""

import logging
from datetime import datetime
from typing import Optional

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
    # ── Category metadata ────────────────────────────────────────────────────
    category_id = event.categories[0].id if event.categories else "default"
    category_title = CATEGORY_MAP.get(category_id, event.categories[0].title if event.categories else "Unknown")

    # ── Step 1: Heuristic pre-scoring ────────────────────────────────────────
    base = float(BASE_SEVERITY.get(category_id, 45))
    geo_count = len(event.geometry)
    severity_score = min(100.0, base + geometry_bonus(geo_count))

    # Extract location data from geometry list
    geom_dicts = [g.model_dump() for g in event.geometry]
    lat, lon = extract_centroid(geom_dicts)
    area = compute_area_proxy(geom_dicts)

    # Boost for large geographic spread
    if area > 10:
        severity_score = min(100.0, severity_score + 10.0)

    risk_level = severity_to_risk(severity_score)
    trend = severity_to_trend(severity_score, geo_count)
    estimated_impact = estimate_impact_description(lat or 30.0, lon or 0.0, area, risk_level)
    heuristic_recs = get_recommendations(category_id, risk_level)

    # Default narrative (heuristic)
    location_str = f"{lat:.1f}°, {lon:.1f}°" if (lat is not None and lon is not None) else "an undisclosed location"
    impact_narrative = (
        f"A {category_title.lower()} event — '{event.title}' — has been detected at {location_str}, "
        f"with {geo_count} tracking data points suggesting {'prolonged or widening activity' if geo_count > 10 else 'recent onset'}. "
        f"Classified as {risk_level} risk (severity {severity_score:.0f}/100), "
        f"this event warrants {'immediate emergency response' if risk_level in ('CRITICAL', 'HIGH') else 'continued monitoring and standard preparedness measures'}."
    )
    recommendations = heuristic_recs
    inference_mode = "heuristic"

    # Confidence: higher when we have location + tracking history
    confidence = 0.65
    if lat is not None:
        confidence += 0.08
    if geo_count > 5:
        confidence += 0.07
    if geo_count > 20:
        confidence += 0.05

    # ── Step 2: Gemini enrichment ─────────────────────────────────────────────
    gemini = _get_gemini()
    if gemini:
        try:
            result = gemini.analyze(event, severity_score, risk_level, lat, lon)
            impact_narrative = result["impact_narrative"]
            recommendations = result["recommendations"]
            trend = result["trend"]
            inference_mode = settings.gemini_model
            confidence = min(0.97, confidence + 0.20)
            logger.info(
                f"gemini_analysis_complete event_id={event.id} "
                f"inference_mode={inference_mode} trend={trend}"
            )
        except GeminiUnavailable as e:
            logger.warning(
                f"gemini_unavailable_fallback event_id={event.id} "
                f"inference_mode=heuristic reason={e}"
            )

    return InferenceResult(
        event_id=event.id,
        category=category_title,
        severity_score=round(severity_score, 1),
        risk_level=risk_level,
        trend=trend,
        estimated_impact=estimated_impact,
        impact_narrative=impact_narrative,
        recommendations=recommendations,
        inference_mode=inference_mode,
        confidence=round(confidence, 2),
        processed_at=datetime.utcnow(),
    )
