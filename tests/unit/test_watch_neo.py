"""End-to-end NEO watch tests (offline: a MockTransport NASA feed + tmp store).

These prove the deterministic NEO sense path works through the *whole* tick —
fetch feed -> pure calc cores -> extract signal -> diff -> persist — with no LLM
anywhere, and that it inherits the loop's idempotency: a close hazardous object
alerts on the first tick and stays quiet on an identical second tick.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from neowatch.config import get_settings
from neowatch.domains.neo import NEO_VERTICAL
from neowatch.watch.runner import WatchRunner
from neowatch.watch.store import WatchStore

_LD_KM = 384_400.0  # 1 lunar distance in km (matches calc.orbital.LUNAR_DISTANCE_KM)


def _neo_item(obj_id: str, name: str, miss_ld: float, diameter_max_m: float, pha: bool) -> dict:
    """A minimal but schema-valid NeoWs ``/feed`` object at a given miss distance."""
    miss_km = miss_ld * _LD_KM
    return {
        "id": obj_id,
        "neo_reference_id": obj_id,
        "name": name,
        "nasa_jpl_url": "https://ssd-api.jpl.nasa.gov/",
        "absolute_magnitude_h": 22.0,
        "estimated_diameter": {
            "kilometers": {
                "estimated_diameter_min": diameter_max_m / 2000.0,
                "estimated_diameter_max": diameter_max_m / 1000.0,
            },
            "meters": {
                "estimated_diameter_min": diameter_max_m / 2.0,
                "estimated_diameter_max": diameter_max_m,
            },
        },
        "is_potentially_hazardous_asteroid": pha,
        "close_approach_data": [
            {
                "close_approach_date": "2026-07-17",
                "relative_velocity": {
                    "kilometers_per_second": 12.0,
                    "kilometers_per_hour": 43200.0,
                },
                "miss_distance": {
                    "astronomical": miss_km / 149_597_870.7,
                    "lunar": miss_ld,
                    "kilometers": miss_km,
                },
                "orbiting_body": "Earth",
            }
        ],
        "is_sentry_object": False,
    }


def _feed(*items: dict[str, Any]) -> dict[str, Any]:
    return {"near_earth_objects": {"2026-07-17": list(items)}}


def _client_returning(payload: Any) -> httpx.AsyncClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


def _wire_neo(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    monkeypatch.setattr(
        "neowatch.watch.rules_neo.get_async_client",
        lambda: _client_returning(payload),
    )


async def test_neo_tick_alerts_on_close_hazard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A close PHA triggers both NEO rules; an identical second tick is silent."""
    settings = _settings(monkeypatch)
    # 0.5 LD (inside the 1.0 LD threshold) and potentially hazardous.
    _wire_neo(monkeypatch, _feed(_neo_item("A", "2026 AA", 0.5, 300.0, pha=True)))
    runner = WatchRunner(settings, WatchStore(tmp_path), verticals=(NEO_VERTICAL,))

    first = await runner.tick()
    keys = {a.key for a in first}
    assert "near-earth-objects:notable-appeared" in keys
    assert "near-earth-objects:close-approach" in keys

    second = await runner.tick()  # same feed, baseline saved -> no edges
    assert second == []
    get_settings.cache_clear()


async def test_neo_tick_persists_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a tick the NEO baseline holds the extracted object signal."""
    settings = _settings(monkeypatch)
    _wire_neo(monkeypatch, _feed(_neo_item("A", "2026 AA", 0.5, 300.0, pha=True)))
    store = WatchStore(tmp_path)
    await WatchRunner(settings, store, verticals=(NEO_VERTICAL,)).tick()

    snap = store.load("near-earth-objects")
    assert snap is not None
    assert snap.signal["closest_id"] == "A"
    assert snap.signal["objects"]["A"]["pha"] is True
    get_settings.cache_clear()


async def test_neo_tick_quiet_on_distant_non_hazard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A distant, low-risk object senses and persists but raises nothing."""
    settings = _settings(monkeypatch)
    _wire_neo(monkeypatch, _feed(_neo_item("B", "2026 BB", 30.0, 5.0, pha=False)))
    store = WatchStore(tmp_path)
    alerts = await WatchRunner(settings, store, verticals=(NEO_VERTICAL,)).tick()

    assert alerts == []
    assert store.load("near-earth-objects") is not None  # still sensed + persisted
    get_settings.cache_clear()
