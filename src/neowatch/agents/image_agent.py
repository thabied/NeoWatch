"""Image agent.

Fetches and prepares NASA APOD images for the report. Searches APOD by date
range, validates each URL is reachable, resizes with Pillow (max 800px wide),
and returns ``ImageAsset`` objects that always carry attribution/credit.

Key concept: no LLM here either — image work is deterministic I/O, so it stays
out of the model entirely. Unreachable images are dropped rather than allowed to
break the report later.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from PIL import Image
from structlog.typing import FilteringBoundLogger

from ..config import Settings
from ..context import AgentContext, AgentResult
from ..data.apod import get_apod_range
from ..data.http import get_async_client
from ..data.models import APODImage
from .base import BaseAgent
from .models import ImageAsset

_MAX_WIDTH = 800


class ImageAgent(BaseAgent):
    """Prepare attributed, resized APOD images for the date range in scope."""

    def __init__(
        self,
        settings: Settings,
        logger: FilteringBoundLogger | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        super().__init__(settings, logger)
        self.cache_dir = cache_dir or Path(".image_cache")

    async def run(self, context: AgentContext) -> AgentResult:
        """Fetch APOD images for the window, validate, resize, and attribute."""
        start, end = self._date_range(context)
        assets: list[ImageAsset] = []
        try:
            async with get_async_client() as client:
                images = await get_apod_range(client, self.settings, start, end)
                for image in images:
                    if image.media_type != "image":
                        continue
                    asset = await self._prepare(client, image)
                    if asset is not None:
                        assets.append(asset)
        except Exception as exc:  # noqa: BLE001 — surface as a typed failure
            self.logger.warning("image_agent.failed", error=str(exc))
            return AgentResult(agent_name="ImageAgent", success=False, error=str(exc))

        self.logger.info("image_agent.prepared", count=len(assets), start=start, end=end)
        return AgentResult(agent_name="ImageAgent", success=True, data=assets)

    async def _prepare(self, client: httpx.AsyncClient, image: APODImage) -> ImageAsset | None:
        """Download, validate, and resize one image; ``None`` if unreachable."""
        url = str(image.url)
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError:
            self.logger.info("image_agent.unreachable", url=url)
            return None  # reject unreachable URLs

        local_path, width, height = self._resize(resp.content, image.date)
        return ImageAsset(
            title=image.title,
            date=image.date,
            url=url,
            hd_url=str(image.hdurl) if image.hdurl else None,
            media_type=image.media_type,
            credit=_credit(image),
            explanation=image.explanation,
            local_path=str(local_path),
            width=width,
            height=height,
        )

    def _resize(self, data: bytes, date: str) -> tuple[Path, int, int]:
        """Resize image bytes to <=800 px wide and save a PNG; return path + size."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(io.BytesIO(data)) as img:
            rgb = img.convert("RGB")
            if rgb.width > _MAX_WIDTH:
                ratio = _MAX_WIDTH / rgb.width
                rgb = rgb.resize((_MAX_WIDTH, round(rgb.height * ratio)))
            out_path = self.cache_dir / f"{date}.png"
            rgb.save(out_path, format="PNG")
            return out_path, rgb.width, rgb.height

    def _date_range(self, context: AgentContext) -> tuple[str, str]:
        cached = context.session_cache.get("image_date_range")
        if isinstance(cached, (tuple, list)) and len(cached) == 2:
            return str(cached[0]), str(cached[1])
        today = datetime.now(UTC).date()
        return (today - timedelta(days=2)).isoformat(), today.isoformat()


def _credit(image: APODImage) -> str:
    """Build the attribution string (APOD copyright when present, else NASA)."""
    holder = image.copyright.strip() if image.copyright else "NASA / APOD"
    return f"{image.title} — credit: {holder}"
