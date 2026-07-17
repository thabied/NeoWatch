"""Unit tests for the NEO watch rules + signal extraction (pure, no I/O).

The NEO rules carry the module's hardest loop-engineering idea — surviving a
*sliding sensing window* — so they get table-driven coverage of every edge:
notable objects appearing (identity set-diff), the non-notable churn staying
silent, the nearest approach crossing a distance threshold with hysteresis, and
the ``prev=None`` first-sight path alerting once on an already-close/hazardous
sky. All of it is a pure function of ``(prev, cur, settings)`` — no network, no
filesystem, no model.
"""

from __future__ import annotations

from typing import Any

from neowatch.calc.models import OrbitalAnalysis, OrbitalReport, RiskAssessment
from neowatch.config import Settings
from neowatch.watch.rules_neo import (
    closest_tightened,
    neo_extract,
    notable_appeared,
)


def _settings(**overrides: Any) -> Settings:
    """A minimal Settings with test secrets; overrides tweak NEO policy thresholds."""
    return Settings(
        anthropic_api_key="sk-ant-test",
        nasa_api_key="nasa-test",
        _env_file=None,
        **overrides,
    )


def _obj(miss_ld: float, *, risk: str = "negligible", pha: bool = False, name: str = "obj") -> dict:
    return {"name": name, "miss_ld": miss_ld, "risk": risk, "pha": pha}


def _signal(objects: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Assemble a NEO signal (mirrors ``neo_extract``'s output shape)."""
    closest_id = min(objects, key=lambda k: objects[k]["miss_ld"]) if objects else None
    return {
        "objects": objects,
        "count": len(objects),
        "closest_ld": objects[closest_id]["miss_ld"] if closest_id else None,
        "closest_id": closest_id,
    }


# --- neo_extract --------------------------------------------------------------


def test_extract_shapes_signal_and_finds_closest() -> None:
    """extract keys by object id, rounds miss distance, and marks the closest."""
    report = OrbitalReport(
        analyses=[
            OrbitalAnalysis(
                object_id="A", name="Alpha", miss_distance_km=1.0, miss_distance_ld=4.5678,
                miss_distance_au=0.0, velocity_km_s=10.0, velocity_class="moderate",
                diameter_min_m=10.0, diameter_max_m=20.0, is_potentially_hazardous=False,
            ),
            OrbitalAnalysis(
                object_id="B", name="Beta", miss_distance_km=1.0, miss_distance_ld=0.9,
                miss_distance_au=0.0, velocity_km_s=10.0, velocity_class="moderate",
                diameter_min_m=10.0, diameter_max_m=20.0, is_potentially_hazardous=True,
            ),
        ],
        risks=[
            RiskAssessment(object_id="A", risk_band="low", risk_score=1, rationale=""),
            RiskAssessment(object_id="B", risk_band="elevated", risk_score=4, rationale=""),
        ],
    )
    sig = neo_extract(report)
    assert sig["count"] == 2
    assert sig["objects"]["A"]["miss_ld"] == 4.568  # rounded to milli-LD
    assert sig["objects"]["B"]["risk"] == "elevated"
    assert sig["closest_id"] == "B" and sig["closest_ld"] == 0.9


def test_extract_empty_report_has_no_closest() -> None:
    sig = neo_extract(OrbitalReport())
    assert sig == {"objects": {}, "count": 0, "closest_ld": None, "closest_id": None}


# --- notable_appeared (object-identity set-diff) ------------------------------


def test_notable_appeared_fires_on_first_sight_hazard() -> None:
    """prev=None with an elevated-risk object already present alerts once."""
    cur = _signal({"A": _obj(5.0, risk="elevated", pha=True, name="2026 AA")})
    alert = notable_appeared(None, cur, _settings())
    assert alert is not None
    assert alert.key == "near-earth-objects:notable-appeared"
    assert alert.previous is None
    assert "2026 AA" in alert.detail


def test_notable_appeared_ignores_distant_pha_with_low_risk() -> None:
    """A PHA far out (low computed risk) is not notable — the moving-window trap."""
    cur = _signal({"A": _obj(80.0, risk="low", pha=True, name="2006 TS7")})
    assert notable_appeared(None, cur, _settings()) is None


def test_notable_appeared_fires_when_new_notable_enters() -> None:
    prev = _signal({"A": _obj(9.0, risk="low")})
    cur = _signal({"A": _obj(9.0, risk="low"), "B": _obj(3.0, risk="elevated", name="2026 BB")})
    alert = notable_appeared(prev, cur, _settings())
    assert alert is not None and "2026 BB" in alert.detail


def test_notable_appeared_ignores_non_notable_newcomer() -> None:
    """A new but low-risk, non-PHA object is routine window churn — stays silent."""
    prev = _signal({"A": _obj(9.0, risk="low")})
    cur = _signal({"A": _obj(9.0, risk="low"), "C": _obj(8.0, risk="low")})
    assert notable_appeared(prev, cur, _settings()) is None


def test_notable_appeared_does_not_refire_for_known_object() -> None:
    """A notable object already seen last tick is not "new" — no re-fire."""
    prev = _signal({"A": _obj(4.0, risk="elevated")})
    cur = _signal({"A": _obj(3.0, risk="elevated")})  # moved closer, same id
    assert notable_appeared(prev, cur, _settings()) is None


def test_notable_appeared_severe_when_new_object_is_high_risk() -> None:
    cur = _signal({"A": _obj(0.5, risk="high", pha=True, name="Big One")})
    alert = notable_appeared(None, cur, _settings())
    assert alert is not None and alert.severity == "severe"


# --- closest_tightened (miss-distance threshold crossing) ---------------------


def test_closest_tightened_fires_on_crossing_inside() -> None:
    prev = _signal({"A": _obj(3.0)})  # nearest was 3 LD, outside 1.0 threshold
    cur = _signal({"A": _obj(0.7, name="Skimmer")})
    alert = closest_tightened(prev, cur, _settings())
    assert alert is not None
    assert alert.key == "near-earth-objects:close-approach"
    assert "Skimmer" in alert.detail


def test_closest_tightened_fires_on_first_sight_when_already_close() -> None:
    cur = _signal({"A": _obj(0.4)})
    assert closest_tightened(None, cur, _settings()) is not None


def test_closest_tightened_silent_when_nothing_close() -> None:
    cur = _signal({"A": _obj(2.0)})
    assert closest_tightened(None, cur, _settings()) is None


def test_closest_tightened_does_not_refire_while_inside() -> None:
    """Hysteresis: once inside the threshold, staying inside does not re-fire."""
    prev = _signal({"A": _obj(0.8)})
    cur = _signal({"A": _obj(0.6)})  # still inside, even closer
    assert closest_tightened(prev, cur, _settings()) is None


def test_closest_tightened_respects_configured_threshold() -> None:
    """A tighter threshold makes a mid-range approach non-alerting."""
    cur = _signal({"A": _obj(0.7)})
    assert closest_tightened(None, cur, _settings(watch_neo_close_ld=0.5)) is None
    assert closest_tightened(None, cur, _settings(watch_neo_close_ld=1.0)) is not None
