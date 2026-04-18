from app.inference.engine import run_inference_batch
from app.models import EONETEvent
from app.config import settings


def _make_event(event_id: str, title: str = "Wildfire") -> EONETEvent:
    return EONETEvent(
        id=event_id,
        title=title,
        description="Synthetic event for batch test",
        link="https://example.com/event",
        categories=[{"id": "wildfires", "title": "Wildfires"}],
        sources=[],
        geometry=[
            {"date": "2026-01-01T00:00:00Z", "type": "Point", "coordinates": [1.0, 2.0]},
            {"date": "2026-01-01T01:00:00Z", "type": "Point", "coordinates": [1.2, 2.1]},
        ],
    )


def test_run_inference_batch_heuristic_mode(monkeypatch):
    monkeypatch.setattr("app.inference.engine._get_gemini", lambda: None)

    events = [_make_event("EONET_BATCH_1"), _make_event("EONET_BATCH_2")]
    results = run_inference_batch(events)

    assert len(results) == 2
    assert results[0].event_id == "EONET_BATCH_1"
    assert results[1].event_id == "EONET_BATCH_2"
    assert all(r.inference_mode == "heuristic" for r in results)


class _BatchGemini:
    def analyze(self, event, severity_score, risk_level, lat, lon):
        return {
            "impact_narrative": f"Batch analysis for {event.id}",
            "recommendations": ["One", "Two", "Three"],
            "trend": "ESCALATING",
        }


def test_run_inference_batch_gemini_mode(monkeypatch):
    monkeypatch.setattr("app.inference.engine._get_gemini", lambda: _BatchGemini())

    events = [_make_event("EONET_BATCH_3"), _make_event("EONET_BATCH_4")]
    results = run_inference_batch(events)

    assert len(results) == 2
    assert all(r.inference_mode == settings.gemini_model for r in results)
    assert all(r.pipeline_path == "TIER_2_GEMINI" for r in results)
