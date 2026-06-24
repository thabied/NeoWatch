"""Live integration tests for the data clients.

These hit real APIs, so they are skipped by default. Run them deliberately with:

    NEOWATCH_RUN_INTEGRATION=1 pytest tests/integration -v

NASA-backed tests also need a valid key in ``.env``. Keyless services (Horizons,
SBDB, arXiv) only need network access.
"""

from __future__ import annotations

import os

import pytest

from neowatch.config import get_settings
from neowatch.data.apod import get_apod
from neowatch.data.arxiv import search_arxiv
from neowatch.data.http import get_async_client
from neowatch.data.neows import get_neo_feed
from neowatch.data.sbdb import get_sbdb

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("NEOWATCH_RUN_INTEGRATION") != "1",
        reason="set NEOWATCH_RUN_INTEGRATION=1 to run live-API tests",
    ),
]


async def test_neows_feed_live() -> None:
    settings = get_settings()
    async with get_async_client() as client:
        items = await get_neo_feed(client, settings, "2024-01-01", "2024-01-02")
    assert items, "expected at least one NEO in a two-day window"
    assert items[0].close_approach_data


async def test_apod_live() -> None:
    settings = get_settings()
    async with get_async_client() as client:
        apod = await get_apod(client, settings, "2024-01-01")
    assert apod.title
    assert apod.media_type in {"image", "video"}


async def test_sbdb_live() -> None:  # keyless
    async with get_async_client() as client:
        record = await get_sbdb(client, "433")
    assert record.fullname.startswith("433")


async def test_arxiv_live() -> None:  # keyless
    async with get_async_client() as client:
        papers = await search_arxiv(client, "all:near earth asteroid", max_results=5)
    assert papers
    assert papers[0].title
