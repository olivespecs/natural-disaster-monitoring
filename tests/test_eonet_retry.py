import pytest
import httpx

from app.eonet.client import fetch_open_events


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("GET", "https://eonet.gsfc.nasa.gov/api/v3/events")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    def json(self):
        return self._payload


class _RetryClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_fetch_open_events_retries_then_succeeds(monkeypatch):
    payload = {
        "events": [
            {
                "id": "EONET_1",
                "title": "Wildfire test",
                "description": "test",
                "link": "https://example.com",
                "categories": [{"id": "wildfires", "title": "Wildfires"}],
                "sources": [],
                "geometry": [{"date": "2026-01-01T00:00:00Z", "type": "Point", "coordinates": [1, 2]}],
            }
        ]
    }

    client = _RetryClient(
        responses=[
            _FakeResponse(503, {}),
            _FakeResponse(200, payload),
        ]
    )
    monkeypatch.setattr("app.eonet.client.httpx.AsyncClient", lambda timeout: client)

    slept = []

    async def _fake_sleep(value):
        slept.append(value)

    monkeypatch.setattr("app.eonet.client.asyncio.sleep", _fake_sleep)

    events = await fetch_open_events(days=1, limit=10)
    assert len(events) == 1
    assert events[0].id == "EONET_1"
    assert client.calls == 2
    assert slept


@pytest.mark.asyncio
async def test_fetch_open_events_retries_on_network_error(monkeypatch):
    request = httpx.Request("GET", "https://eonet.gsfc.nasa.gov/api/v3/events")
    network_error = httpx.RequestError("network down", request=request)
    client = _RetryClient(responses=[network_error, _FakeResponse(200, {"events": []})])
    monkeypatch.setattr("app.eonet.client.httpx.AsyncClient", lambda timeout: client)

    async def _fake_sleep(value):
        return None

    monkeypatch.setattr("app.eonet.client.asyncio.sleep", _fake_sleep)

    events = await fetch_open_events(days=1, limit=10)
    assert events == []
    assert client.calls == 2
