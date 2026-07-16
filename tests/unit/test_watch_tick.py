"""End-to-end tick tests (offline: MockTransport feeds + a tmp_path store).

These prove the two properties the whole watch loop rests on:

- **Idempotency.** Run ``tick()`` twice against identical feeds: alerts fire on
  the first pass and *not* the second, because the first pass persisted the
  baseline and the edge is gone.
- **Error isolation.** If one vertical's fetch fails, the tick still processes the
  other, and the failing vertical's baseline is left untouched (not poisoned).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from neowatch.config import get_settings
from neowatch.domains.registry import watched_verticals
from neowatch.watch.runner import WatchRunner
from neowatch.watch.store import WatchStore

# A single Kp row at 6.0 -> G2 storm (is_storm True) -> storm-onset should fire.
_STORM_KP_FEED = [
    {"time_tag": "2026-07-16T00:00:00", "Kp": 6.0, "a_running": 60, "station_count": 8}
]


def _eonet_event(event_id: str, lon: float, lat: float) -> dict[str, Any]:
    return {
        "id": event_id,
        "title": f"Wildfire {event_id}",
        "description": None,
        "link": f"https://eonet.gsfc.nasa.gov/api/v3/events/{event_id}",
        "closed": None,
        "categories": [{"id": "wildfires", "title": "Wildfires"}],
        "geometry": [
            {
                "magnitudeValue": None,
                "magnitudeUnit": None,
                "date": "2026-07-16T00:00:00Z",
                "type": "Point",
                "coordinates": [lon, lat],
            }
        ],
    }


# Two wildfires ~300 km apart cluster into a hotspot -> hotspot-onset should fire.
_CLUSTER_EONET_FEED: dict[str, Any] = {
    "title": "EONET Events",
    "events": [
        _eonet_event("A", -111.96, 43.83),
        _eonet_event("B", -116.18, 43.63),
    ],
}


def _client_returning(payload: Any, status: int = 200) -> httpx.AsyncClient:
    """An httpx client whose every request returns ``payload`` (or a status code)."""
    def handler(_request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


def _wire_feeds(
    monkeypatch: pytest.MonkeyPatch,
    *,
    kp_status: int = 200,
) -> None:
    """Point both LLM-free agents at their MockTransport feeds."""
    monkeypatch.setattr(
        "neowatch.agents.space_weather_agent.get_async_client",
        lambda: _client_returning(_STORM_KP_FEED, status=kp_status),
    )
    monkeypatch.setattr(
        "neowatch.agents.earth_events_agent.get_async_client",
        lambda: _client_returning(_CLUSTER_EONET_FEED),
    )


async def test_tick_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """First tick raises alerts; an identical second tick raises none."""
    settings = _settings(monkeypatch)
    _wire_feeds(monkeypatch)
    runner = WatchRunner(settings, WatchStore(tmp_path), verticals=watched_verticals())

    first = await runner.tick()
    keys = {a.key for a in first}
    assert "space-weather:storm-onset" in keys
    assert "earth-events:hotspot-onset" in keys

    second = await runner.tick()
    assert second == []  # baselines saved -> no edges -> nothing re-fires
    get_settings.cache_clear()


async def test_tick_persists_baselines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After a tick, both watched verticals have a persisted snapshot."""
    settings = _settings(monkeypatch)
    _wire_feeds(monkeypatch)
    store = WatchStore(tmp_path)
    await WatchRunner(settings, store, verticals=watched_verticals()).tick()

    sw = store.load("space-weather")
    ev = store.load("earth-events")
    assert sw is not None and sw.signal["is_storm"] is True
    assert ev is not None and ev.signal["hotspot_present"] is True
    get_settings.cache_clear()


async def test_one_vertical_failure_does_not_abort_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing fetch for one vertical is isolated: the other still alerts + persists."""
    settings = _settings(monkeypatch)
    _wire_feeds(monkeypatch, kp_status=500)  # space-weather fetch fails
    store = WatchStore(tmp_path)
    alerts = await WatchRunner(settings, store, verticals=watched_verticals()).tick()

    keys = {a.key for a in alerts}
    assert "earth-events:hotspot-onset" in keys  # healthy vertical still fired
    assert not any(k.startswith("space-weather") for k in keys)
    # The failing vertical's baseline was never written (not poisoned).
    assert store.load("space-weather") is None
    assert store.load("earth-events") is not None
    get_settings.cache_clear()
