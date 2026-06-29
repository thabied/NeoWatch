"""Image agent.

Fetches and prepares NASA imagery for the report. It tries the NASA Image &
Video Library first, searching on the *topic* of the query (so "an image of
Apophis" returns asteroid imagery, not that day's picture); if the query has no
usable topic, or the search finds nothing, it falls back to Astronomy Picture of
the Day for the date range in scope. Every image is validated as reachable,
resized with Pillow (max 800 px wide), and returned as an attributed
``ImageAsset``.

Key concept: no LLM here — image work is deterministic I/O, so it stays out of
the model entirely. The search-first / APOD-fallback shape is the lesson: prefer
the topical source, but degrade to the always-available one rather than returning
nothing. Unreachable images are dropped, not allowed to break the report later.
"""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from PIL import Image
from structlog.typing import FilteringBoundLogger

from ..config import Settings
from ..context import AgentContext, AgentResult
from ..data.apod import get_apod_range
from ..data.http import get_async_client
from ..data.images import search_nasa_images
from ..data.models import APODImage, NASAImage
from .base import BaseAgent
from .models import ImageAsset

_MAX_WIDTH = 800
_SEARCH_LIMIT = 3

# Words that signal "I want a picture" but carry no subject — stripped so the
# search query is just the topic (e.g. "show me an image of Apophis" -> "apophis").
# If nothing survives the strip, there is no topic to search, so we use APOD.
_IMAGERY_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "for", "me", "us", "i", "you", "please",
        "show", "give", "get", "see", "view", "find", "want", "need", "can",
        "could", "would", "some", "any", "this", "week", "today",
        "image", "images", "picture", "pictures", "photo", "photos",
        "photograph", "photographs", "visual", "visuals", "pic", "pics",
    }
)


class ImageAgent(BaseAgent):
    """Prepare attributed, resized NASA imagery — topical first, APOD as fallback."""

    def __init__(
        self,
        settings: Settings,
        logger: FilteringBoundLogger | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        super().__init__(settings, logger)
        # Resolve to an absolute path so ``local_path`` is unambiguous: Gradio's
        # gallery resolves served files against its allow-list, and a relative
        # path would be checked against the server's cwd rather than ours.
        self.cache_dir = (cache_dir or Path(settings.image_cache_dir)).resolve()

    async def run(self, context: AgentContext) -> AgentResult:
        """Fetch topical imagery (or APOD), validate, resize, and attribute."""
        try:
            async with get_async_client() as client:
                assets = await self._from_search(client, context)
                if not assets:
                    # No topic, or the search found nothing usable — fall back to
                    # the always-available date-range source.
                    assets = await self._from_apod(client, context)
        except Exception as exc:  # noqa: BLE001 — surface as a typed failure
            self.logger.warning("image_agent.failed", error=str(exc))
            return AgentResult(agent_name="ImageAgent", success=False, error=str(exc))

        self.logger.info("image_agent.prepared", count=len(assets))
        return AgentResult(agent_name="ImageAgent", success=True, data=assets)

    async def _from_search(
        self, client: httpx.AsyncClient, context: AgentContext
    ) -> list[ImageAsset]:
        """Search the NASA Image Library on the query's topic; empty if no topic."""
        terms = _search_terms(context.query)
        if not terms:
            return []
        images = await search_nasa_images(client, terms, limit=_SEARCH_LIMIT)
        self.logger.info("image_agent.search", terms=terms, hits=len(images))
        assets: list[ImageAsset] = []
        for image in images:
            asset = await self._prepare_search(client, image)
            if asset is not None:
                assets.append(asset)
        return assets

    async def _from_apod(
        self, client: httpx.AsyncClient, context: AgentContext
    ) -> list[ImageAsset]:
        """Fall back to APOD for the date range in scope."""
        start, end = self._date_range(context)
        images = await get_apod_range(client, self.settings, start, end)
        assets: list[ImageAsset] = []
        for image in images:
            if image.media_type != "image":
                continue
            asset = await self._prepare_apod(client, image)
            if asset is not None:
                assets.append(asset)
        return assets

    async def _prepare_apod(
        self, client: httpx.AsyncClient, image: APODImage
    ) -> ImageAsset | None:
        """Download, validate, and resize one APOD image; ``None`` if unreachable."""
        url = str(image.url)
        data = await self._download(client, url)
        if data is None:
            return None
        local_path, width, height = self._resize(data, image.date)
        return ImageAsset(
            title=image.title,
            date=image.date,
            url=url,
            hd_url=str(image.hdurl) if image.hdurl else None,
            media_type=image.media_type,
            credit=_apod_credit(image),
            explanation=image.explanation,
            local_path=str(local_path),
            width=width,
            height=height,
        )

    async def _prepare_search(
        self, client: httpx.AsyncClient, image: NASAImage
    ) -> ImageAsset | None:
        """Download, validate, and resize one search result; ``None`` if unreachable."""
        url = str(image.preview_url)
        data = await self._download(client, url)
        if data is None:
            return None
        # nasa_id is a stable, unique filename; date_created is an ISO datetime so
        # we keep just the date for display.
        local_path, width, height = self._resize(data, image.nasa_id)
        return ImageAsset(
            title=image.title,
            date=image.date_created[:10],
            url=url,
            hd_url=None,
            media_type="image",
            credit=_search_credit(image),
            explanation=image.description,
            local_path=str(local_path),
            width=width,
            height=height,
        )

    async def _download(self, client: httpx.AsyncClient, url: str) -> bytes | None:
        """Fetch image bytes; ``None`` (and a log line) if the URL is unreachable."""
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError:
            self.logger.info("image_agent.unreachable", url=url)
            return None
        return resp.content

    def _resize(self, data: bytes, name: str) -> tuple[Path, int, int]:
        """Resize image bytes to <=800 px wide and save a PNG; return path + size."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(io.BytesIO(data)) as img:
            rgb = img.convert("RGB")
            if rgb.width > _MAX_WIDTH:
                ratio = _MAX_WIDTH / rgb.width
                rgb = rgb.resize((_MAX_WIDTH, round(rgb.height * ratio)))
            out_path = self.cache_dir / f"{_safe_name(name)}.png"
            rgb.save(out_path, format="PNG")
            return out_path, rgb.width, rgb.height

    def _date_range(self, context: AgentContext) -> tuple[str, str]:
        cached = context.session_cache.get("image_date_range")
        if isinstance(cached, (tuple, list)) and len(cached) == 2:
            return str(cached[0]), str(cached[1])
        today = datetime.now(UTC).date()
        return (today - timedelta(days=2)).isoformat(), today.isoformat()


def _search_terms(query: str) -> str:
    """Reduce a query to its topic by dropping imagery filler words.

    Returns an empty string when nothing but filler remains, which the agent
    reads as "no topic — use APOD" rather than running a meaningless search.
    """
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in _IMAGERY_STOPWORDS]
    return " ".join(words)


def _safe_name(name: str) -> str:
    """Make a filesystem-safe stem from an id/date (NASA ids can contain spaces)."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return cleaned or "image"


def _apod_credit(image: APODImage) -> str:
    """Build the attribution string (APOD copyright when present, else NASA)."""
    holder = image.copyright.strip() if image.copyright else "NASA / APOD"
    return f"{image.title} — credit: {holder}"


def _search_credit(image: NASAImage) -> str:
    """Build the attribution string for a NASA Image Library result."""
    holder = image.photographer or image.center or "NASA"
    return f"{image.title} — credit: {holder}"
