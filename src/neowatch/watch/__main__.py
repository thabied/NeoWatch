"""Command-line entry point for the watch loop.

Run with ``python -m neowatch.watch``. Three modes, one ``tick``:

- ``--once`` (or no flag): run a single tick and exit. The **exit code reflects
  whether alerts fired** (0 = nothing new, 1 = alerts raised), so an *external*
  scheduler — cron, a GitHub Actions ``schedule:`` job, a Claude Code ``/schedule``
  routine — can act on the result. The on-disk store is what carries state between
  these one-shot runs.
- ``--interval N``: run ``run_forever`` for a persistent host (an in-process
  sleeper), ticking every ``N`` seconds until interrupted.
- ``--dry-run``: sense and diff but **persist nothing and emit to no sink** — a
  safe way to see what *would* fire. Incompatible with ``--interval``.

This is the "policy vs mechanism" split made concrete: the same ``tick`` runs
under an in-process loop *or* any external scheduler, because state lives in the
store and the tick is idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

import structlog

from ..config import get_settings
from ..logging_config import configure_logging
from .models import Alert
from .runner import WatchRunner
from .sinks import AlertSink, JsonlSink, LogSink
from .store import WatchStore


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m neowatch.watch",
        description="NeoWatch watch loop — sense each domain, diff vs last run, alert on change.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single tick and exit (default). Exit code: 0=no alerts, 1=alerts fired.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        metavar="SECONDS",
        help="Run continuously, ticking every SECONDS until interrupted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sense and diff but persist nothing and emit to no sink. Not with --interval.",
    )
    args = parser.parse_args(argv)
    if args.dry_run and args.interval is not None:
        parser.error("--dry-run cannot be combined with --interval (dry runs are single ticks).")
    return args


def _print_summary(alerts: list[Alert], *, dry_run: bool) -> None:
    """Print a concise human summary of a single tick's alerts to stdout."""
    prefix = "[dry-run] " if dry_run else ""
    if not alerts:
        print(f"{prefix}No new alerts.")
        return
    print(f"{prefix}{len(alerts)} alert(s):")
    for alert in alerts:
        print(f"  - [{alert.severity}] {alert.vertical}: {alert.title} — {alert.detail}")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, run the requested mode, and return a process exit code."""
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger("neowatch.watch")

    store = WatchStore(settings.watch_state_dir)
    runner = WatchRunner(settings, store)
    sinks: list[AlertSink] = [LogSink(), JsonlSink(store)]

    if args.interval is not None:
        logger.info("watch.cli.interval", interval=args.interval)
        try:
            asyncio.run(runner.run_forever(args.interval, sinks=sinks))
        except KeyboardInterrupt:
            logger.info("watch.cli.interrupted")
        return 0

    # Single-tick modes: --once, --dry-run, or the bare default.
    logger.info("watch.cli.once", dry_run=args.dry_run)
    alerts = asyncio.run(
        runner.tick(
            sinks=() if args.dry_run else sinks,
            persist=not args.dry_run,
        )
    )
    _print_summary(alerts, dry_run=args.dry_run)
    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
