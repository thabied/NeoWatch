"""Fetch agent.

Retrieves structured NEO data from NASA APIs (Claude Haiku driving a tool-use
loop over the fetch tools). Applies the spec's chunking rule: sort the feed by
miss distance, enumerate the top 10, and summarise the rest as a count.

Key concept: a cheap model (Haiku) is enough for "which data do I need" tool
decisions; the heavy reasoning is reserved for Sonnet elsewhere. The model picks
tools and arguments; Python executes them against the typed Phase 2 clients.
"""

from __future__ import annotations

import json
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolParam
from structlog.typing import FilteringBoundLogger

from ..config import Settings
from ..context import AgentContext, AgentResult
from ..data.http import NasaRateLimiter, get_async_client
from ..data.models import EphemerisData, NEODetail, NEOFeedItem, SpaceWeatherReport
from ..llm import get_anthropic_client
from ..tools.fetch_tools import FetchResult, dispatch_fetch_tool, to_tool_result_text
from ..tools.schemas import FETCH_TOOLS
from .base import BaseAgent
from .models import NEOData

_FETCH_SYSTEM = (
    "You gather near-Earth-object data for a research report by calling the "
    "provided tools. Start with get_neo_feed to find approaching objects, then "
    "call other tools only if the query needs detail, space weather, or an "
    "ephemeris. Keep date ranges to 7 days or fewer. Stop once you have the data "
    "the query asks for; do not chat."
)
_MAX_ITERATIONS = 6
_TOP_N = 10  # spec chunking rule: enumerate the 10 closest, summarise the rest


class FetchAgent(BaseAgent):
    """Drive a Haiku tool-use loop to assemble typed ``NEOData``."""

    def __init__(
        self,
        settings: Settings,
        logger: FilteringBoundLogger | None = None,
        client: AsyncAnthropic | None = None,
        rate_limiter: NasaRateLimiter | None = None,
    ) -> None:
        super().__init__(settings, logger)
        self.client = client
        self.rate_limiter = rate_limiter

    async def run(self, context: AgentContext) -> AgentResult:
        """Let Haiku call fetch tools, capturing every typed result it triggers."""
        anthropic = self.client or get_anthropic_client(self.settings)
        feed: list[NEOFeedItem] = []
        details: list[NEODetail] = []
        ephemerides: list[EphemerisData] = []
        weather: SpaceWeatherReport | None = None

        messages: list[dict[str, Any]] = [{"role": "user", "content": context.query}]
        try:
            async with get_async_client() as http:
                for _ in range(_MAX_ITERATIONS):
                    # We build the API payload as plain dicts; cast at the boundary
                    # because the SDK's TypedDicts are stricter than our hand-built
                    # JSON-schema dicts (e.g. extra input_schema keys).
                    #
                    # cache_control here turns on top-level auto-caching: the SDK
                    # marks the last cacheable block (the growing message history)
                    # as an ephemeral cache breakpoint. The raw NASA tool results
                    # we carry across iterations (~4.8k tokens, above Haiku 4.5's
                    # 4096-token cache minimum) are then re-read at ~0.1x on every
                    # iteration after the first instead of paying full input price
                    # each loop. Verify on a live run via
                    # resp.usage.cache_read_input_tokens > 0 on later iterations.
                    resp = await anthropic.messages.create(
                        model=self.settings.haiku_model,
                        max_tokens=1024,
                        system=_FETCH_SYSTEM,
                        tools=cast("list[ToolParam]", FETCH_TOOLS),
                        messages=cast("list[MessageParam]", messages),
                        cache_control={"type": "ephemeral"},
                    )
                    if resp.usage is not None:
                        context.add_tokens(resp.usage.input_tokens, resp.usage.output_tokens)
                    if resp.stop_reason != "tool_use":
                        # end_turn is the normal exit. max_tokens (Haiku's 1024 cap)
                        # or refusal mean we stopped mid-gather and may assemble from
                        # partial data — log it instead of failing quietly.
                        if resp.stop_reason in ("max_tokens", "refusal"):
                            self.logger.warning(
                                "fetch_agent.early_stop", stop_reason=resp.stop_reason
                            )
                        break

                    messages.append({"role": "assistant", "content": resp.content})
                    tool_results: list[dict[str, Any]] = []
                    for block in resp.content:
                        if block.type != "tool_use":
                            continue
                        result, text, is_error = await self._call(http, context, block)
                        if not is_error and result is not None:
                            _capture(result, feed, details, ephemerides)
                            if isinstance(result, SpaceWeatherReport):
                                weather = result
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": text,
                                "is_error": is_error,
                            }
                        )
                    messages.append({"role": "user", "content": tool_results})
        except Exception as exc:  # noqa: BLE001 — surface as a typed failure
            self.logger.warning("fetch_agent.failed", error=str(exc))
            return AgentResult(agent_name="FetchAgent", success=False, error=str(exc))

        neo_data = _assemble(feed, details, ephemerides, weather)
        self.logger.info(
            "fetch_agent.done",
            kept=len(neo_data.feed_items),
            remainder=neo_data.remainder_count,
        )
        return AgentResult(agent_name="FetchAgent", success=True, data=neo_data)

    async def _call(
        self, http: Any, context: AgentContext, block: Any
    ) -> tuple[FetchResult | None, str, bool]:
        """Execute one tool_use block, with session-cache dedupe and error capture."""
        cache_key = f"{block.name}:{json.dumps(block.input, sort_keys=True)}"
        cached = context.session_cache.get(cache_key)
        if cached is not None:
            return cached, to_tool_result_text(cached), False
        try:
            result = await dispatch_fetch_tool(
                block.name, dict(block.input), http, self.settings, self.rate_limiter
            )
        except Exception as exc:  # noqa: BLE001 — feed the error back so Haiku can adapt
            self.logger.info("fetch_agent.tool_error", tool=block.name, error=str(exc))
            return None, f"Error running {block.name}: {exc}", True
        context.session_cache[cache_key] = result
        return result, to_tool_result_text(result), False


def _capture(
    result: FetchResult,
    feed: list[NEOFeedItem],
    details: list[NEODetail],
    ephemerides: list[EphemerisData],
) -> None:
    """Sort a tool result into the running typed buckets."""
    if isinstance(result, NEODetail):
        details.append(result)
    elif isinstance(result, EphemerisData):
        ephemerides.append(result)
    elif isinstance(result, list):
        feed.extend(result)


def _assemble(
    feed: list[NEOFeedItem],
    details: list[NEODetail],
    ephemerides: list[EphemerisData],
    weather: SpaceWeatherReport | None,
) -> NEOData:
    """Apply the chunking rule: dedupe, keep the 10 closest, count the remainder."""
    unique = {item.id: item for item in feed}
    ranked = sorted(unique.values(), key=_closest_miss_km)
    kept = ranked[:_TOP_N]
    remainder = max(0, len(ranked) - _TOP_N)
    return NEOData(
        feed_items=kept,
        remainder_count=remainder,
        details=details,
        ephemerides=ephemerides,
        space_weather=weather,
    )


def _closest_miss_km(item: NEOFeedItem) -> float:
    return min(
        (ca.miss_distance.kilometers for ca in item.close_approach_data),
        default=float("inf"),
    )
