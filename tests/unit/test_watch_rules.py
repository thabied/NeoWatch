"""Unit tests for the watch rules (pure, no I/O — the loop's decision logic).

Rules are the whole point of the loop-engineering phase, so they get exhaustive
table-driven coverage: every edge fires exactly once, the non-edges stay silent,
and the "first sight" (``prev=None``) path still alerts on an already-active
condition. Because rules are pure functions of ``(prev, cur, settings)``, none of
this touches the network, the filesystem, or an LLM.
"""

from __future__ import annotations

from typing import Any

from neowatch.config import Settings
from neowatch.watch.rules_earth_events import event_surge, new_hotspot
from neowatch.watch.rules_space_weather import (
    extract as sw_extract,
)
from neowatch.watch.rules_space_weather import (
    storm_cleared,
    storm_escalation,
    storm_onset,
)


def _settings(**overrides: Any) -> Settings:
    """A minimal Settings with test secrets; overrides tweak policy thresholds."""
    return Settings(
        anthropic_api_key="sk-ant-test",
        nasa_api_key="nasa-test",
        _env_file=None,
        **overrides,
    )


def _sw(kp: float, g: str, level: str, storm: bool) -> dict[str, Any]:
    return {"kp": kp, "g_scale": g, "storm_level": level, "is_storm": storm}


_QUIET = _sw(2.0, "G0", "none", False)
_G1 = _sw(5.0, "G1", "minor", True)
_G2 = _sw(6.0, "G2", "moderate", True)
_G4 = _sw(8.0, "G4", "severe", True)
_G5 = _sw(9.0, "G5", "extreme", True)


# --- space-weather: onset -----------------------------------------------------


def test_onset_fires_on_first_sight_storm() -> None:
    """prev=None with an already-active storm still alerts once (first sight)."""
    alert = storm_onset(None, _G2, _settings())
    assert alert is not None
    assert alert.key == "space-weather:storm-onset"
    assert alert.previous is None


def test_onset_fires_on_quiet_to_storm_transition() -> None:
    alert = storm_onset(_QUIET, _G1, _settings())
    assert alert is not None and alert.severity == "warning"


def test_onset_silent_while_storm_persists() -> None:
    """An ongoing storm is not a fresh onset — no re-fire (idempotency)."""
    assert storm_onset(_G1, _G2, _settings()) is None


def test_onset_silent_when_quiet() -> None:
    assert storm_onset(_QUIET, _QUIET, _settings()) is None


def test_onset_respects_raised_gscale_threshold() -> None:
    """With the threshold set to G3, a G2 storm is below the bar and stays silent."""
    assert storm_onset(_QUIET, _G2, _settings(watch_kp_alert_gscale="G3")) is None


# --- space-weather: escalation ------------------------------------------------


def test_escalation_fires_when_band_rises() -> None:
    alert = storm_escalation(_G1, _G2, _settings())
    assert alert is not None and alert.key == "space-weather:storm-escalation"


def test_escalation_is_severe_at_g4_plus() -> None:
    alert = storm_escalation(_G2, _G5, _settings())
    assert alert is not None and alert.severity == "severe"


def test_escalation_silent_when_band_unchanged() -> None:
    assert storm_escalation(_G2, _G2, _settings()) is None


def test_escalation_silent_from_quiet() -> None:
    assert storm_escalation(_QUIET, _G2, _settings()) is None


# --- space-weather: cleared ---------------------------------------------------


def test_cleared_fires_on_storm_to_quiet() -> None:
    alert = storm_cleared(_G4, _QUIET, _settings())
    assert alert is not None and alert.severity == "info"


def test_cleared_silent_when_no_prior_storm() -> None:
    assert storm_cleared(_QUIET, _QUIET, _settings()) is None
    assert storm_cleared(None, _QUIET, _settings()) is None


def test_sw_extract_keeps_only_signal_fields() -> None:
    """extract reduces the full assessment to the four alert-relevant fields."""
    from neowatch.calc.space_weather import assess_space_weather
    from neowatch.data.models import KpReading

    signal = sw_extract(assess_space_weather(KpReading(time_tag="t", kp=6.0)))
    assert set(signal) == {"kp", "g_scale", "storm_level", "is_storm"}
    assert signal["g_scale"] == "G2" and signal["is_storm"] is True


# --- earth-events: surge ------------------------------------------------------


def _ev(total: int, hotspot: bool = False, count: int = 0) -> dict[str, Any]:
    return {
        "total_active": total,
        "top_category": "Wildfires",
        "hotspot_present": hotspot,
        "hotspot_count": count,
    }


def test_surge_fires_on_first_sight_above_threshold() -> None:
    """prev=None (treated as 0) with a count already above threshold alerts once."""
    alert = event_surge(None, _ev(60), _settings())
    assert alert is not None and alert.key == "earth-events:surge"


def test_surge_fires_on_upward_crossing() -> None:
    assert event_surge(_ev(40), _ev(60), _settings()) is not None


def test_surge_silent_while_sustained() -> None:
    """Already above threshold last tick -> no re-fire this tick (edge-triggered)."""
    assert event_surge(_ev(60), _ev(70), _settings()) is None


def test_surge_silent_below_threshold() -> None:
    assert event_surge(_ev(10), _ev(40), _settings()) is None


# --- earth-events: hotspot ----------------------------------------------------


def test_hotspot_fires_when_cluster_appears() -> None:
    alert = new_hotspot(_ev(30, hotspot=False), _ev(30, hotspot=True, count=8), _settings())
    assert alert is not None and alert.key == "earth-events:hotspot-onset"


def test_hotspot_fires_on_first_sight() -> None:
    assert new_hotspot(None, _ev(30, hotspot=True, count=5), _settings()) is not None


def test_hotspot_silent_when_already_present() -> None:
    prev = _ev(30, hotspot=True, count=5)
    cur = _ev(30, hotspot=True, count=9)
    assert new_hotspot(prev, cur, _settings()) is None


def test_hotspot_silent_when_absent() -> None:
    assert new_hotspot(_ev(30, hotspot=False), _ev(30, hotspot=False), _settings()) is None
