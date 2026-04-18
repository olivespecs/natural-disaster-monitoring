"""Gemini API integration for LLM-powered natural event analysis."""

import json
import logging
from typing import Optional

from google import genai
from google.genai import types as genai_types

from app.config import settings
from app.models import EONETEvent

logger = logging.getLogger(__name__)


class GeminiUnavailable(Exception):
    """Raised when Gemini API is not configured, unavailable, or fails."""
    pass


class GeminiAnalyzer:
    """Wraps Gemini API to analyse natural events and generate risk assessments."""

    def __init__(self):
        if not settings.gemini_api_key:
            raise GeminiUnavailable("GEMINI_API_KEY is not configured")
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model_name = settings.gemini_model
        logger.info(f"GeminiAnalyzer initialized with model: {self.model_name}")

    def analyze(
        self,
        event: EONETEvent,
        severity_score: float,
        risk_level: str,
        lat: Optional[float],
        lon: Optional[float],
    ) -> dict:
        """
        Call Gemini to analyse a natural event.

        Returns a dict with keys:
          - impact_narrative (str)
          - recommendations (list[str])
          - trend (str: STABLE | ESCALATING | DECLINING)
        """
        category_title = event.categories[0].title if event.categories else "Natural Event"
        first_date = event.geometry[0].date if event.geometry else "Unknown date"
        geometry_count = len(event.geometry)
        location_str = f"{lat:.2f}°, {lon:.2f}°" if (lat is not None and lon is not None) else "location unknown"

        prompt = f"""You are a senior disaster risk analyst at a global emergency response centre.
A NASA Earth Observatory Natural Event Tracker (EONET) event has been detected in real time.

=== EVENT DATA ===
Title: {event.title}
Category: {category_title}
Location: {location_str}
First detected: {first_date}
Tracking data points: {geometry_count}  (higher = longer active duration or wider geographic spread)
Pre-scored severity: {severity_score:.1f} / 100
Pre-assessed risk level: {risk_level}

=== YOUR TASK ===
1. Write a concise 2-sentence impact assessment explaining the nature of this event and its potential consequences for people and infrastructure.
2. Provide exactly 3 specific, actionable emergency response recommendations appropriate for the risk level.
3. Based on the tracking data and severity, assess the trend: STABLE, ESCALATING, or DECLINING.

=== OUTPUT FORMAT ===
Respond ONLY with a valid JSON object — no markdown, no explanation, no extra text:
{{
  "impact_narrative": "Two-sentence impact assessment here.",
  "recommendations": ["Specific recommendation 1", "Specific recommendation 2", "Specific recommendation 3"],
  "trend": "ESCALATING"
}}"""

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.25,
                    max_output_tokens=600,
                ),
            )
            raw = response.text.strip()

            # Strip markdown code fences if present
            if raw.startswith("```"):
                parts = raw.split("```")
                # parts[1] contains the content between first pair of fences
                raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

            result = json.loads(raw)

            # Validate structure
            required = {"impact_narrative", "recommendations", "trend"}
            if not required.issubset(result.keys()):
                raise ValueError(f"Missing keys in Gemini response: {required - result.keys()}")

            if not isinstance(result["recommendations"], list) or len(result["recommendations"]) < 1:
                raise ValueError("recommendations must be a non-empty list")

            # Normalize trend
            trend = str(result.get("trend", "STABLE")).upper()
            if trend not in {"STABLE", "ESCALATING", "DECLINING"}:
                trend = "STABLE"
            result["trend"] = trend

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Gemini returned invalid JSON for event {event.id}: {e}\nRaw: {raw[:200]}")
            raise GeminiUnavailable(f"Invalid JSON from Gemini: {e}")
        except Exception as e:
            logger.error(f"Gemini API call failed for event {event.id}: {type(e).__name__}: {e}")
            raise GeminiUnavailable(str(e))
