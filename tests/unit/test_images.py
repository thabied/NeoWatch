"""Unit tests for the NASA Image Library search parser (offline, pure).

The search response is heterogeneous, so ``parse_image_search`` must flatten the
usable rows and skip anything missing the bits we need rather than raising.
"""

from __future__ import annotations

from neowatch.data.images import parse_image_search


def test_parses_a_well_formed_item() -> None:
    """A complete item flattens to one NASAImage with its preview URL and credit."""
    payload = {
        "collection": {
            "items": [
                {
                    "data": [
                        {
                            "nasa_id": "PIA12345",
                            "title": "Asteroid Apophis",
                            "date_created": "2021-03-05T00:00:00Z",
                            "media_type": "image",
                            "center": "JPL",
                            "secondary_creator": "NASA/JPL-Caltech",
                        }
                    ],
                    "links": [{"href": "https://images-assets.nasa.gov/x/x~thumb.jpg"}],
                }
            ]
        }
    }
    results = parse_image_search(payload)
    assert len(results) == 1
    img = results[0]
    assert img.nasa_id == "PIA12345"
    assert str(img.preview_url) == "https://images-assets.nasa.gov/x/x~thumb.jpg"
    assert img.photographer == "NASA/JPL-Caltech"  # falls back to secondary_creator


def test_skips_unusable_items() -> None:
    """Items missing data/links, or that aren't images, are dropped — not raised."""
    payload = {
        "collection": {
            "items": [
                {"data": [], "links": [{"href": "https://x/y.jpg"}]},  # no metadata
                {"data": [{"nasa_id": "a", "media_type": "image"}], "links": []},  # no link
                {
                    "data": [{"nasa_id": "b", "title": "clip", "media_type": "video"}],
                    "links": [{"href": "https://x/v.mp4"}],
                },  # not an image
            ]
        }
    }
    assert parse_image_search(payload) == []


def test_empty_collection_is_empty() -> None:
    """A collection with no items (a search miss) yields no results."""
    assert parse_image_search({"collection": {"items": []}}) == []
    assert parse_image_search({}) == []
