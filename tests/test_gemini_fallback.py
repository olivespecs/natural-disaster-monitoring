from app.inference.engine import run_inference
from app.inference.gemini_analyzer import GeminiUnavailable
from app.models import EONETEvent


class _FailingGemini:
    def analyze(self, event, severity_score, risk_level, lat, lon):
        raise GeminiUnavailable("forced failure for test")


def _make_event() -> EONETEvent:
    return EONETEvent(
        id="EONET_FALLBACK_1",
        title="Test volcanic activity",
        description="Synthetic event for test",
        link="https://example.com/event",
        categories=[{"id": "volcanoes", "title": "Volcanoes"}],
        sources=[],
        geometry=[
            {"date": "2026-01-01T00:00:00Z", "type": "Point", "coordinates": [140.0, 35.0]},
            {"date": "2026-01-01T01:00:00Z", "type": "Point", "coordinates": [140.2, 35.1]},
        ],
    )


def test_run_inference_falls_back_to_heuristic(monkeypatch):
    monkeypatch.setattr("app.inference.engine._get_gemini", lambda: _FailingGemini())
    result = run_inference(_make_event())
    assert result.inference_mode == "heuristic"
    assert result.trend in {"STABLE", "ESCALATING", "DECLINING"}
    assert isinstance(result.recommendations, list)
    assert result.recommendations
