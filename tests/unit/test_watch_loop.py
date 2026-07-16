"""Unit tests for the loop driver, sink threading, and the CLI (all offline).

The loop's headline properties are availability (a tick error never kills it),
clean cancellation, and that alerts reach the sinks. The CLI tests pin the
policy-vs-mechanism surface: a single tick's exit code reflects alerts, and a dry
run mutates nothing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from neowatch.calc.geo import assess_earth_events
from neowatch.calc.space_weather import assess_space_weather
from neowatch.config import get_settings
from neowatch.data.models import KpReading
from neowatch.domains.base import Vertical
from neowatch.domains.registry import watched_verticals
from neowatch.watch import __main__ as cli
from neowatch.watch.models import Alert
from neowatch.watch.runner import WatchRunner
from neowatch.watch.store import WatchStore


def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    get_settings.cache_clear()
    return get_settings()


async def _fake_sense(_self: WatchRunner, vertical: Vertical) -> object:
    """Return a canned assessment per vertical — a G2 storm, and calm Earth."""
    if vertical.name == "space-weather":
        return assess_space_weather(KpReading(time_tag="t", kp=6.0))
    return assess_earth_events([])  # empty feed -> no Earth alerts


class _RecordingSink:
    """Captures every batch it is emitted (a test double for AlertSink)."""

    def __init__(self) -> None:
        self.batches: list[list[Alert]] = []

    def emit(self, alerts: Any) -> None:
        self.batches.append(list(alerts))


class _BadSink:
    """A sink that always raises — used to prove sink error-isolation."""

    def emit(self, alerts: Any) -> None:
        raise RuntimeError("sink boom")


# --- sink threading through tick() -------------------------------------------


async def test_tick_threads_alerts_to_sinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tick routes its computed alerts to every sink."""
    settings = _settings(monkeypatch)
    monkeypatch.setattr(WatchRunner, "sense_vertical", _fake_sense)
    runner = WatchRunner(settings, WatchStore(tmp_path), verticals=watched_verticals())
    sink = _RecordingSink()

    await runner.tick(sinks=[sink])

    assert len(sink.batches) == 1
    keys = {a.key for a in sink.batches[0]}
    assert keys == {"space-weather:storm-onset"}  # storm fired; Earth was calm
    get_settings.cache_clear()


async def test_a_failing_sink_does_not_starve_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One raising sink is logged and skipped; healthy sinks still receive alerts."""
    settings = _settings(monkeypatch)
    monkeypatch.setattr(WatchRunner, "sense_vertical", _fake_sense)
    runner = WatchRunner(settings, WatchStore(tmp_path), verticals=watched_verticals())
    good = _RecordingSink()

    await runner.tick(sinks=[_BadSink(), good])  # must not raise

    assert good.batches and good.batches[0][0].key == "space-weather:storm-onset"
    get_settings.cache_clear()


# --- run_forever driver -------------------------------------------------------


async def test_loop_survives_tick_error_and_cancels_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raised tick error is swallowed; the loop keeps ticking until cancelled."""
    settings = _settings(monkeypatch)
    runner = WatchRunner(settings, WatchStore(tmp_path), verticals=())
    calls: list[int] = []

    async def counting_tick(*, sinks: Any = (), persist: bool = True) -> list[Alert]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient tick failure")
        return []

    monkeypatch.setattr(runner, "tick", counting_tick)

    task = asyncio.create_task(runner.run_forever(0.001, sinks=[]))
    await asyncio.sleep(0.05)  # let it spin through several ticks
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(calls) >= 2  # survived the first-tick error and continued
    get_settings.cache_clear()


# --- CLI ----------------------------------------------------------------------


def test_cli_rejects_dry_run_with_interval() -> None:
    """--dry-run and --interval are mutually exclusive (argparse errors out)."""
    with pytest.raises(SystemExit):
        cli._parse_args(["--dry-run", "--interval", "5"])


def test_cli_once_reports_alerts_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--once` fires the storm alert (exit 1), and persists a baseline + audit."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    monkeypatch.setenv("WATCH_STATE_DIR", str(tmp_path / "state"))
    get_settings.cache_clear()
    monkeypatch.setattr(WatchRunner, "sense_vertical", _fake_sense)

    code = cli.main(["--once"])
    assert code == 1  # alerts fired
    out = capsys.readouterr().out
    assert "storm" in out.lower()
    store = WatchStore(tmp_path / "state")
    assert store.load("space-weather") is not None  # baseline persisted
    assert [a.key for a in store.read_alerts()] == ["space-weather:storm-onset"]
    get_settings.cache_clear()


def test_cli_dry_run_persists_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--dry-run` senses and diffs but writes no state and emits to no sink."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NASA_API_KEY", "nasa-test")
    state_dir = tmp_path / "state"
    monkeypatch.setenv("WATCH_STATE_DIR", str(state_dir))
    get_settings.cache_clear()
    monkeypatch.setattr(WatchRunner, "sense_vertical", _fake_sense)

    code = cli.main(["--dry-run"])
    assert code == 1  # would-be alerts still reflected in the exit code
    assert "[dry-run]" in capsys.readouterr().out
    assert not state_dir.exists()  # nothing persisted at all
    get_settings.cache_clear()
