"""NASA Image & Video Library client.

Topic search over ``images-api.nasa.gov`` — used to fetch imagery that matches
the *subject* of a query (e.g. "asteroid", "Apophis") rather than whatever the
Astronomy Picture of the Day happened to be for a calendar window. No API key is
required (this is a different host from the keyed ``api.nasa.gov`` endpoints, so
it is not counted against the NeoWs rate limit).

Key concept: the search response is deeply nested and heterogeneous, so parsing
is defensive — results missing the bits we need are skipped, never raised.
"""

from __future__ import annotations

from typing import Any

import httpx

from .http import retry_external
from .models import NASAImage

_BASE = "https://images-api.nasa.gov/search"


def parse_image_search(data: dict[str, Any]) -> list[NASAImage]:
    """Flatten the nested search payload into ``NASAImage`` rows.

    Each ``collection.items[]`` entry carries its metadata in ``data[0]`` and its
    preview URL in ``links[0].href``. Items missing either, or that aren't images,
    are skipped rather than allowed to raise.
    """
    items = data.get("collection", {}).get("items", [])
    results: list[NASAImage] = []
    for item in items:
        records = item.get("data") or []
        links = item.get("links") or []
        if not records or not links:
            continue
        meta = records[0]
        preview = links[0].get("href")
        if meta.get("media_type") != "image" or not preview:
            continue
        results.append(
            NASAImage(
                nasa_id=str(meta.get("nasa_id", "")),
                title=str(meta.get("title", "")),
                date_created=str(meta.get("date_created", "")),
                media_type="image",
                preview_url=preview,
                description=str(meta.get("description", "")),
                center=meta.get("center"),
                photographer=meta.get("photographer") or meta.get("secondary_creator"),
            )
        )
    return results


@retry_external
async def search_nasa_images(
    client: httpx.AsyncClient, query: str, limit: int = 3
) -> list[NASAImage]:
    """Search the NASA Image Library for ``query``, returning up to ``limit`` images."""
    resp = await client.get(_BASE, params={"q": query, "media_type": "image"})
    resp.raise_for_status()
    return parse_image_search(resp.json())[:limit]
