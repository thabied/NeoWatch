# NeoWatch — Watch Loop Runbook

How to *operate* the watch loop. For the design and the concepts behind it, see
[`WATCH_LOOP_PLAN.md`](WATCH_LOOP_PLAN.md).

The watcher is one command with three modes, all around a single idempotent
`tick()`:

```bash
python -m neowatch.watch --once        # run one tick and exit
python -m neowatch.watch --dry-run     # sense + diff only; persist nothing, emit nowhere
python -m neowatch.watch --interval N  # in-process loop: tick every N seconds until interrupted
```

- **Exit code (single-tick modes):** `0` = no new alerts, `1` = alerts fired. An
  external scheduler can branch on this.
- **State:** `.watch_state/<vertical>.json` (one baseline per domain) plus
  `.watch_state/alerts.jsonl` (append-only audit). Override the location with
  `WATCH_STATE_DIR`. This on-disk state is what lets separate `--once` runs behave
  as one continuous watch.
- **Thresholds (policy):** `WATCH_KP_ALERT_GSCALE` (default `G1`),
  `WATCH_EVENTS_ACTIVE_THRESHOLD` (default `50`), and for NEO
  `WATCH_NEO_HORIZON_DAYS` (default `7`, the close-approach scan window) and
  `WATCH_NEO_CLOSE_LD` (default `1.0`, the "close approach" distance in lunar
  distances). See `.env.example`.
- **Keys:** the space-weather and earth-events verticals are keyless; the **NEO**
  vertical needs `NASA_API_KEY`. If it is absent the NEO fetch fails and that one
  vertical is skipped for the tick (logged, baseline untouched) — the keyless
  domains still run.

---

## Policy vs mechanism

The loop's *policy* (what to watch, what counts as an alert) lives in the code and
`.env`. Its *mechanism* (who invokes the tick, how often) is entirely up to you.
Below are four mechanisms driving the exact same `--once` tick. Pick one.

### 1. In-process loop (persistent host)

Simplest when you have a machine that stays up (a small VM, a container):

```bash
python -m neowatch.watch --interval 10800   # every 3 hours
```

Ctrl-C (or a `SIGTERM` to the process) shuts it down cleanly. In a container this
is just the entrypoint; the loop survives transient fetch errors and keeps going.

### 2. cron (single-shot, external scheduler)

No long-running process — cron fires a one-shot tick and the on-disk state carries
the baseline forward:

```cron
# m h dom mon dow   command   (every 3 hours; adjust paths)
0 */3 * * *  cd /opt/neowatch && /opt/neowatch/.venv/bin/python -m neowatch.watch --once >> /var/log/neowatch-watch.log 2>&1
```

### 3. GitHub Actions (`schedule:`)

Runs in CI on a cron schedule. Commit the workflow below as
`.github/workflows/watch.yml`. Store the two keys as repository secrets.

```yaml
name: neowatch-watch
on:
  schedule:
    - cron: "0 */3 * * *"   # every 3 hours (UTC)
  workflow_dispatch: {}       # allow manual runs too

jobs:
  tick:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e .
      - name: Restore watch state
        uses: actions/cache@v4
        with:
          path: .watch_state
          key: watch-state           # a single moving key: last run's state restored, this run's saved
      - name: Run one tick
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          NASA_API_KEY: ${{ secrets.NASA_API_KEY }}
        run: python -m neowatch.watch --once
```

> Note: `actions/cache` is best-effort, not durable storage. For a real
> deployment prefer cron/a host with a persistent volume, or push `alerts.jsonl`
> to an artifact/store. The cache keeps the *baseline* warm enough that edge
> detection works between scheduled runs.

### 4. Claude Code routine (`/schedule`)

If you drive NeoWatch from Claude Code, a scheduled routine can run the one-shot
tick on a cron cadence:

```
/schedule create "neowatch-watch" --cron "0 */3 * * *" \
  --prompt "Run: python -m neowatch.watch --once, then summarise any alerts."
```

The same `--once` tick, invoked by yet another mechanism — the policy never moved.

---

## What an alert looks like

`alerts.jsonl` holds one JSON object per raised alert, e.g.:

```json
{"vertical":"space-weather","key":"space-weather:storm-onset","severity":"warning","title":"Geomagnetic storm onset","detail":"Geomagnetic storm began: Kp 6.00 (G2, moderate).","raised_at":"2026-07-16T00:00:00+00:00","previous":{"kp":2.0,"g_scale":"G0","is_storm":false},"current":{"kp":6.0,"g_scale":"G2","is_storm":true}}
```

Alert keys currently emitted:

| key | when it fires |
|---|---|
| `space-weather:storm-onset` | quiet → storm (at/above `WATCH_KP_ALERT_GSCALE`) |
| `space-weather:storm-escalation` | storm strengthens to a higher G band |
| `space-weather:storm-cleared` | storm → quiet |
| `earth-events:surge` | active-event count crosses `WATCH_EVENTS_ACTIVE_THRESHOLD` upward |
| `earth-events:hotspot-onset` | a spatial cluster of events appears where there was none |
| `near-earth-objects:notable-appeared` | an elevated/high computed-risk object newly enters the scan window |
| `near-earth-objects:close-approach` | the nearest approach crosses inside `WATCH_NEO_CLOSE_LD` |

Because rules are **edge-triggered**, each fires on the *transition* only — a
sustained storm or surge alerts once, not every tick.
