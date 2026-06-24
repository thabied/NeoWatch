"""Unit tests for the data layer: parsers, retry policy, and rate limiter.

These run fully offline — parsers are tested against saved fixtures, so a change
in an API's JSON is caught here without any network access.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from neowatch.data import http as http_module
from neowatch.data.arxiv import parse_arxiv
from neowatch.data.donki import parse_flares
from neowatch.data.http import NasaRateLimiter, retry_external
from neowatch.data.neows import parse_neo_feed
from neowatch.data.sbdb import parse_sbdb

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_json(name: str) -> object:
    return json.loads((_FIXTURES / name).read_text())


# --- Parser tests (offline, against fixtures) --------------------------------


def test_parse_neo_feed() -> None:
    """The date-keyed feed flattens into typed NEOs with coerced numerics."""
    items = parse_neo_feed(_load_json("neows_feed.json"))  # type: ignore[arg-type]
    assert len(items) == 1
    neo = items[0]
    assert neo.name == "465633 (2009 JR5)"
    assert neo.is_potentially_hazardous_asteroid is True
    # NASA sends velocity as a string; the model coerces it to float.
    assert isinstance(neo.close_approach_data[0].relative_velocity.kilometers_per_second, float)
    assert neo.estimated_diameter.kilometers.estimated_diameter_max == pytest.approx(0.4783)


def test_parse_sbdb_flattens_nested_json() -> None:
    """Nested SBDB JSON is flattened; Y/N-style flags normalize to bool."""
    record = parse_sbdb(_load_json("sbdb.json"))  # type: ignore[arg-type]
    assert record.fullname.startswith("433 Eros")
    assert record.neo is True
    assert record.pha is False
    assert record.orbit_class == "Amor"
    assert len(record.phys_par) == 2
    assert record.phys_par[0].name == "H"


def test_parse_flares() -> None:
    """DONKI flare records normalize onto the common event model."""
    events = parse_flares(_load_json("donki_flr.json"))  # type: ignore[arg-type]
    assert len(events) == 2
    assert events[0].event_type == "FLR"
    assert events[1].detail == "X2.0"


def test_parse_arxiv() -> None:
    """Atom XML parses into typed papers with authors and categories."""
    papers = parse_arxiv((_FIXTURES / "arxiv.xml").read_text())
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "A Survey of Near-Earth Object Detection Methods"
    assert paper.authors == ["Jane Doe", "John Smith"]
    assert "astro-ph.EP" in paper.categories


# --- Retry policy -------------------------------------------------------------


async def test_retry_external_attempts_three_times() -> None:
    """A persistently failing call is retried exactly 3 times, then re-raises."""
    calls = 0

    @retry_external
    async def flaky() -> None:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("boom")

    with pytest.raises(httpx.ConnectError):
        await flaky()
    assert calls == 3


# --- Rate limiter -------------------------------------------------------------


def test_rate_limiter_counts_and_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """The limiter counts calls in the rolling hour and warns past the threshold."""
    fake_logger = Mock()
    monkeypatch.setattr(http_module, "logger", fake_logger)

    limiter = NasaRateLimiter(warn_threshold=3)
    for _ in range(2):
        limiter.record()
    assert limiter.count == 2
    fake_logger.warning.assert_not_called()

    limiter.record()  # crosses the threshold
    assert limiter.count == 3
    fake_logger.warning.assert_called_once()
