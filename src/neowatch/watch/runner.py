"""``WatchRunner`` — the deterministic tick that senses, diffs, and alerts.

This module contains the loop's *brain* but not yet the loop itself: ``tick()``
is one full pass over every watched vertical, and it is the unit of correctness
and the unit of test. The recurring driver (``run_forever``) and pluggable sinks
arrive in Phase C; the seam for them (per-vertical error isolation) is built here.

The tick is a straight line per vertical: **sense -> extract -> load baseline ->
run rules -> save new baseline**. Two properties are deliberate:

- **Idempotent.** Because rules are edge-triggered and the new baseline is saved
  at the end, a second identical tick sees ``prev == cur`` and raises nothing.
- **Error-isolated.** Each vertical is wrapped in try/except: a fetch failure is
  logged and skipped, and — crucially — the failing vertical's baseline is left
  *untouched* (we ``continue`` before saving), so one flaky source can never
  poison another domain's state or abort the whole tick.

The watcher is a **second consumer of the deterministic cores**: it runs a
vertical's specialist agent directly and reads the typed assessment straight from
``AgentResult.data`` — never through the orchestrator/synthesis LLM pipeline.
(Parking results on ``session_cache`` is the orchestrator's job, which we bypass.)
For the two LLM-free verticals this is keyless and network-cheap.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Sequence

import structlog
from structlog.typing import FilteringBoundLogger

from ..config import Settings
from ..context import AgentContext
from ..domains.base import Vertical
from ..domains.registry import watched_verticals
from .models import Alert, WatchSnapshot
from .sinks import AlertSink
from .spec import utc_now_iso
from .store import WatchStore


class WatchSenseError(RuntimeError):
    """Raised when a vertical's agent could not produce an assessment this tick."""


class WatchRunner:
    """Runs the deterministic watch tick over a set of watchable verticals."""

    def __init__(
        self,
        settings: Settings,
        store: WatchStore,
        *,
        verticals: tuple[Vertical, ...] | None = None,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        """Bind the runner to its settings, store, and the verticals to watch.

        Args:
            settings: Shared application settings (also carries the alert-policy
                thresholds the rules read).
            store: The durable snapshot/alert store (Phase A).
            verticals: The watchable verticals to tick. Defaults to every vertical
                in the registry that declares a ``WatchSpec``; injectable so tests
                can watch a curated subset.
            logger: Optional structlog logger.
        """
        self.settings = settings
        self.store = store
        self._verticals = verticals if verticals is not None else watched_verticals()
        self.logger: FilteringBoundLogger = logger or structlog.get_logger("neowatch.watch")

    async def sense_vertical(self, vertical: Vertical) -> object:
        """Run the vertical's agent and return its typed assessment.

        Builds the vertical's first capability's agent (no Anthropic client — the
        watched verticals are LLM-free), runs it against a throwaway context, and
        returns the typed assessment from ``AgentResult.data``.

        Note: an agent returns its payload in ``result.data`` — parking it on
        ``session_cache`` is the *orchestrator's* job (``_dispatch``), which the
        watcher deliberately bypasses. So we read ``data`` directly rather than the
        blackboard.

        Raises:
            WatchSenseError: if the agent reports failure or returns no payload.
        """
        capability = vertical.capabilities[0]
        agent = capability.build_agent(self.settings, None)
        context = AgentContext(query=f"[watch] {vertical.name}")
        result = await agent.run(context)
        if not result.success:
            raise WatchSenseError(result.error or f"{vertical.name}: agent reported failure")
        if result.data is None:
            raise WatchSenseError(f"{vertical.name}: agent returned no assessment")
        return result.data

    async def tick(
        self,
        *,
        sinks: Sequence[AlertSink] = (),
        persist: bool = True,
    ) -> list[Alert]:
        """Run one deterministic pass over all watched verticals; return raised alerts.

        Per vertical: sense -> extract signal -> load previous baseline -> run every
        rule -> persist the new baseline. Each vertical is isolated: a failure is
        logged and skipped without touching that vertical's saved baseline or the
        others. The collected alerts are then routed to every sink.

        Args:
            sinks: Alert destinations (log, JSONL audit, …). Emitting is itself
                error-isolated so a bad sink can't lose alerts from the others.
            persist: When False (a *dry run*), baselines are not saved — the tick
                senses and diffs for inspection without mutating state. Pass no
                sinks alongside it to also suppress emission.
        """
        alerts: list[Alert] = []
        for vertical in self._verticals:
            spec = vertical.watch
            if spec is None:  # not watchable — skip defensively
                continue
            try:
                assessment = await self.sense_vertical(vertical)
                signal = spec.extract(assessment)
                previous = self.store.load(vertical.name)
                prev_signal = previous.signal if previous is not None else None

                for rule in spec.rules:
                    alert = rule(prev_signal, signal, self.settings)
                    if alert is not None:
                        alerts.append(alert)

                if persist:
                    snapshot = WatchSnapshot(
                        vertical=vertical.name,
                        captured_at=utc_now_iso(),
                        signal=signal,
                        fingerprint=WatchSnapshot.fingerprint_of(signal),
                    )
                    self.store.save(snapshot)
            except Exception as exc:  # noqa: BLE001 — error isolation is the point
                # One vertical's failure must never abort the tick or poison state.
                self.logger.warning(
                    "watch.tick.vertical_failed", vertical=vertical.name, error=str(exc)
                )
                continue

        self._emit(alerts, sinks)
        self.logger.info(
            "watch.tick.done",
            watched=len(self._verticals),
            alerts=len(alerts),
            persisted=persist,
        )
        return alerts

    def _emit(self, alerts: list[Alert], sinks: Sequence[AlertSink]) -> None:
        """Route alerts to each sink, isolating a failing sink from the rest."""
        for sink in sinks:
            try:
                sink.emit(alerts)
            except Exception as exc:  # noqa: BLE001 — one bad sink must not lose the others
                self.logger.error(
                    "watch.sink.failed", sink=type(sink).__name__, error=str(exc)
                )

    async def run_forever(
        self,
        interval: float,
        *,
        sinks: Sequence[AlertSink] = (),
        jitter: float = 0.0,
    ) -> None:
        """Tick every ``interval`` seconds until cancelled — the recurring driver.

        This is the *mechanism* wrapped around the tick's *policy*. Its defining
        property is availability: it must never die on a transient error. So each
        tick is guarded — any ``Exception`` (a tick's own per-vertical isolation is
        belt; this is braces) is logged and the loop sleeps and tries again.

        ``asyncio.CancelledError`` derives from ``BaseException``, not
        ``Exception``, so it slips past that guard and unwinds to the outer handler,
        giving a clean, traceback-free shutdown when the task is cancelled (Ctrl-C,
        a signal handler, or a test cancelling the task).

        Args:
            interval: Base seconds between ticks.
            sinks: Alert destinations, threaded into each ``tick``.
            jitter: Max extra random seconds added per sleep, to avoid many
                watchers hammering a source in lockstep (thundering herd).
        """
        self.logger.info("watch.loop.start", interval=interval, jitter=jitter)
        try:
            while True:
                try:
                    await self.tick(sinks=sinks)
                except Exception as exc:  # noqa: BLE001 — the loop must outlive any tick error
                    self.logger.error("watch.loop.tick_failed", error=str(exc))
                await asyncio.sleep(interval + random.uniform(0.0, jitter))
        except asyncio.CancelledError:
            self.logger.info("watch.loop.stopped")
            raise
