# NeoWatch — The Watch Loop (Phased Plan)

**Status:** Pre-implementation
**Theme:** *Loop & harness engineering* (the companion topic to the context
engineering already documented across `PLAN.md`, `RETRIEVAL_CONCEPTS.md`, and
`IMPROVEMENTS.md`).
**Audience:** the developer, learning by building. Same learning-mode rules as
`PLAN.md` apply: narrate **What / Why / Trade-offs / Tools** inline per step,
append a short entry to `docs/LEARNING_LOG.md` per phase, teaching docstrings on
new classes, and end every phase green (`ruff` + `mypy` + offline `pytest`).

---

## 0. Why this feature — and what it teaches

NeoWatch is named a *watch*, but today it never watches anything: every run is a
single, stateless request→report. This feature adds the missing outer layer — a
**recurring, stateful loop** that periodically senses each science domain,
detects what *changed* since last time, and raises alerts.

It is deliberately chosen to practise the two topics the codebase is currently
thin on:

- **Loop engineering — the *outer* loop.** The orchestrator's tool-use loop
  (`orchestrator.py`) is an *inner* loop: many steps inside one query. This
  feature is the *outer* loop: one cheap step repeated across time. Different
  discipline — cadence, convergence-by-idempotency, edge- vs level-triggering,
  flap avoidance.
- **Harness engineering — the scaffolding around the model.** A loop that
  survives process restarts needs **state that lives outside the context
  window**: a durable store, atomic writes, a tick that is idempotent, and a
  clean split between *policy* (what/when to check) and *mechanism* (who calls
  the tick — an in-process sleeper, cron, or a scheduled cloud agent).

> The north-star discipline carried over from the rest of NeoWatch: **the loop's
> decisions are 100% deterministic** (pure diffing over typed assessments). Any
> LLM involvement is an *optional* human-readable garnish on already-decided
> alerts — never in the decision path. Same anti-hallucination stance as the
> synthesis/fact-check design.

### Concepts primer (the vocabulary this plan uses)

| Concept | Meaning here | Where it shows up |
|---|---|---|
| **Tick** | One full pass: sense → snapshot → diff → alert → persist. The atomic, testable unit. | Phase B `WatchRunner.tick()` |
| **Snapshot / baseline** | The last-persisted watch signal per domain; the thing "current" is diffed against. | Phase A `WatchStore` |
| **Fingerprint** | A stable string over the alert-relevant fields — cheap "did anything change?" check. | Phase A `WatchSnapshot` |
| **Edge-triggered** | Alert fires on a *transition* (below→above a threshold). Inherently idempotent: no transition next tick → no re-fire. **Preferred.** | Phase B rules |
| **Level-triggered** | Alert fires while a condition *holds*. Re-fires every tick unless suppressed → needs cooldown state. **Avoided first.** | discussed, deferred |
| **Hysteresis** | Different on/off thresholds (fire at G1, clear below G1) so a value hovering on a boundary doesn't flap. | Phase B space-weather rules |
| **Idempotency** | Two identical ticks back-to-back produce alerts only once. The core correctness property. | Phase B tests |
| **Policy vs mechanism** | *Policy* = what to watch and how often. *Mechanism* = who invokes the tick (async sleeper / cron / cloud routine). Decoupled so the same `tick()` runs under any driver. | Phase C |
| **Sink** | A pluggable alert destination (log, JSONL audit, markdown digest, later an LLM digest). | Phase C |
| **Error isolation** | One domain's fetch failure must not kill the loop or other domains. | Phase C |

---

## 1. Design overview

### 1.1 The pipeline the watcher reuses (and what it bypasses)

The watcher is a **second consumer of the existing deterministic cores** — it
does *not* go through the orchestrator/synthesis LLM pipeline. For each watched
vertical it:

1. builds the vertical's specialist agent from the registry
   (`capability.build_agent(settings, client)`),
2. runs it (`await agent.run(context)`), which fetches + computes and parks a
   typed assessment on `context.session_cache[capability.cache_key]`,
3. reads that typed assessment back out and **extracts a small watch signal**
   from it.

For the two LLM-free verticals — **space-weather** (`SpaceWeatherAssessment`)
and **earth-events** (`EarthEventsAssessment`) — this whole path is **keyless,
network-cheap, and needs no Anthropic client**. That is why they are the first
(and only Phase-B) watch targets. NEO is deferred (§Phase D): it needs the
FetchAgent→CalcAgent chain, the NASA key, and per-object identity diffing.

> **Trade-off (scope):** starting with the two deterministic verticals means the
> first shippable loop is fully offline-testable and free to run. NEO is more
> valuable to a user but drags in the LLM fetch loop and a harder diff (object
> identity, not a scalar) — worth its own phase, not the MVP.

### 1.2 How a domain declares that it is watchable

Mirror the existing optional `contribute` hook on `Vertical`: add an **optional
`watch: WatchSpec | None = None`** field. A vertical with no `WatchSpec` is
simply not watched — same "declare a Vertical, don't edit the framework" ethos
that Phase 0 established. No second registry.

```
WatchSpec (per vertical):
  extract(assessment) -> dict          # typed assessment  ->  JSON-able signal
  rules: tuple[AlertRule, ...]         # each: (prev_signal|None, cur_signal) -> Alert | None
  cadence_seconds: int                 # how often this domain is worth re-checking
```

`extract` keeps the persisted snapshot tiny and decoupled from the full
assessment model (so a later field addition doesn't silently change diffs).
`rules` are **pure functions** — trivially unit-testable, no I/O.

### 1.3 State model

```
WatchSnapshot            # one persisted baseline per vertical
  vertical: str
  captured_at: str       # ISO-8601 UTC
  signal: dict[str, Any] # output of WatchSpec.extract
  fingerprint: str       # stable hash over the alert-relevant signal fields

Alert
  vertical: str
  key: str               # stable id, e.g. "space-weather:storm-onset" (for dedup/audit)
  severity: str          # info | watch | warning | severe
  title: str
  detail: str
  raised_at: str         # ISO-8601 UTC
  previous: dict | None  # the signal values that triggered the edge
  current: dict
```

### 1.4 The store (harness durability)

`WatchStore` persists **one JSON file per vertical** under a git-ignored
`watch_state_dir` (default `.watch_state/`), plus an append-only
`alerts.jsonl` audit trail. Two durability rules, both taught explicitly:

- **Atomic writes:** write to `foo.json.tmp`, `os.replace()` onto `foo.json`.
  `os.replace` is atomic on POSIX, so a crash mid-write can never leave a
  half-written baseline that corrupts the next diff.
- **Missing baseline = "first sight", not an error.** The very first tick for a
  domain has no previous snapshot; rules receive `prev=None`. Onset rules treat
  `None` as "below threshold" so a storm that is *already* raging on first run
  still alerts once (a deliberate policy choice — documented in the rule).

### 1.5 The tick and the loop

```
WatchRunner.tick() -> list[Alert]      # one deterministic pass over all watched verticals
WatchRunner.run_forever(interval)      # while not cancelled: tick(); sleep(interval)
```

`tick()` is the unit of correctness and the unit of test. `run_forever` is a
thin driver around it. **Per-vertical error isolation** lives in `tick()`: a
fetch failure for one domain is caught, logged, and skipped — it never aborts
the tick or poisons the other domains' baselines.

### 1.6 Two drivers (policy vs mechanism)

Same `tick()`, two ways to invoke it:

1. **In-process sleeper** — `python -m neowatch.watch --interval 10800` runs
   `run_forever` for a persistent host.
2. **One-shot** — `python -m neowatch.watch --once` runs a single `tick()` and
   exits, for an *external* scheduler: `cron`, a GitHub Actions
   `schedule:` workflow, a Claude Code `/schedule` routine, or `ScheduleWakeup`.
   The on-disk store is what makes state survive between one-shot invocations.

> **The harness lesson:** because state is external and `tick()` is idempotent,
> the loop's *mechanism* is swappable without touching its *policy*. That
> decoupling is the whole point of harness engineering.

---

## 2. Phases

Each phase is independently shippable, ends green, and gets a LEARNING_LOG entry.

### Phase A — State & models (harness scaffolding, no behaviour yet)

**Objective.** Stand up the durable substrate: config, the snapshot/alert
models, and the atomic-write store. Nothing senses or alerts yet — this phase
is pure, offline-testable harness plumbing.

**Files to create**
- `src/neowatch/watch/__init__.py`
- `src/neowatch/watch/models.py` — `WatchSnapshot`, `Alert` (Pydantic v2).
- `src/neowatch/watch/store.py` — `WatchStore` (load/save per vertical, atomic
  write, `append_alerts` to `alerts.jsonl`).
- `tests/unit/test_watch_store.py`

**Files to edit**
- `src/neowatch/config.py` — add `watch_state_dir: str = ".watch_state"`,
  `watch_interval_seconds: int = 10_800` (3h), and the per-domain threshold
  tunables (`watch_kp_alert_gscale: str = "G1"`,
  `watch_events_active_threshold: int = 50`).
- `.env.example` — document the new TUNABLES.
- `.gitignore` — add `.watch_state/`.

**Steps**
1. `models.py`: define `WatchSnapshot` and `Alert` with docstrings that state
   *why* each field exists (esp. `fingerprint` and `key`).
2. `store.py`: `WatchStore(base_dir)` with `load(vertical) -> WatchSnapshot |
   None`, `save(snapshot)` (atomic via tmp + `os.replace`), and
   `append_alerts(alerts)`. Create `base_dir` lazily.
3. Config + `.env.example` + `.gitignore` edits.
4. Tests: round-trip save→load; `load` of an absent vertical returns `None`;
   an atomic-write test (save twice, assert no `.tmp` left, second read wins);
   `append_alerts` appends valid JSON lines.

**Verification checklist**
- [ ] `WatchStore` round-trips a snapshot; absent vertical → `None`.
- [ ] No `.tmp` file remains after a save; concurrent-ish double save leaves one valid file.
- [ ] `.watch_state/` is git-ignored; `.env.example` documents every new setting.
- [ ] `ruff` + `mypy src/` clean; new unit tests pass (suite still fully offline).

---

### Phase B — Watch signals, rules, and the tick (the loop's brain)

**Objective.** Make the two LLM-free verticals watchable and implement the
deterministic `tick()`. This is the core loop-engineering phase: edge-triggering,
hysteresis, and idempotency.

**Files to create**
- `src/neowatch/watch/spec.py` — `WatchSpec` + `AlertRule` type (the descriptor).
- `src/neowatch/watch/runner.py` — `WatchRunner` with `sense_vertical()` and
  `tick()` (no loop yet).
- `src/neowatch/watch/rules_space_weather.py` — extract + rules.
- `src/neowatch/watch/rules_earth_events.py` — extract + rules.
- `tests/unit/test_watch_rules.py`, `tests/unit/test_watch_tick.py`

**Files to edit**
- `src/neowatch/domains/base.py` — add optional `watch: WatchSpec | None = None`
  to `Vertical` (import guarded to avoid a cycle — mirror how `contribute` is
  typed).
- `src/neowatch/domains/space_weather.py`, `.../earth_events.py` — attach a
  `WatchSpec`.
- `src/neowatch/domains/registry.py` — add `watched_verticals()` accessor
  (verticals whose `watch is not None`).

**Steps**
1. `spec.py`: define `AlertRule = Callable[[dict | None, dict], Alert | None]`
   and the `WatchSpec` dataclass (`extract`, `rules`, `cadence_seconds`).
2. `rules_space_weather.py`:
   - `extract(a: SpaceWeatherAssessment) -> dict`: `{kp, g_scale, storm_level,
     is_storm}`.
   - Rules (edge-triggered, with hysteresis via the discrete G-scale bands):
     **storm onset** (`prev` not-storm/`None` → `cur.is_storm`), **escalation**
     (G-scale index increased while stormy), **cleared** (`prev` storm → `cur`
     not storm). Threshold from `settings.watch_kp_alert_gscale`.
3. `rules_earth_events.py`:
   - `extract(a: EarthEventsAssessment) -> dict`: `{total_active, top_category,
     hotspot_present, hotspot_count}`.
   - Rules: **surge** (`total_active` crosses `watch_events_active_threshold`
     upward), **new hotspot** (`prev` none/absent → `cur` present, or count jumps
     ≥ N), **new dominant category**. Keep the first cut to surge + hotspot-onset.
4. Attach `WatchSpec`s to the two verticals; add `watched_verticals()`.
5. `runner.py`:
   - `sense_vertical(vertical)`: build the (first) capability's agent, run it on
     a throwaway `AgentContext`, return the typed assessment from `session_cache`.
   - `tick()`: for each watched vertical → sense → `extract` → build
     `WatchSnapshot` → `store.load` prev → run rules → collect alerts →
     `store.save` new snapshot. Wrap each vertical in try/except (error
     isolation) — Phase C hardens this, but the seam is here.
6. Tests:
   - `test_watch_rules.py`: table-driven prev/current dicts → exact expected
     alerts (onset / escalation / clear / surge / none). Pure, no I/O.
   - `test_watch_tick.py`: with a `tmp_path` store and MockTransport feeds, run
     `tick()` twice — assert alerts fire on the first tick and **not** the second
     (idempotency), and that a fetch failure for one vertical doesn't stop the
     other.

**Verification checklist**
- [ ] Rules are pure and edge-triggered; hysteresis prevents flap across a Kp boundary.
- [ ] Two identical ticks → alerts once (idempotency), proven by test.
- [ ] First-ever tick with a storm already active still alerts once (`prev=None` path).
- [ ] One vertical's fetch error doesn't abort the tick.
- [ ] `ruff` + `mypy src/` clean; suite fully offline (MockTransport + `tmp_path`).

---

### Phase C — The loop, drivers, and sinks (the outer harness)

**Objective.** Wrap `tick()` in a real recurring loop, expose both drivers, and
route alerts to pluggable sinks. This is the harness/scheduling phase.

**Files to create**
- `src/neowatch/watch/sinks.py` — `AlertSink` protocol + `LogSink`, `JsonlSink`.
- `src/neowatch/watch/__main__.py` — CLI: `--once` / `--interval N` /
  `--dry-run`.
- `tests/unit/test_watch_loop.py`, `tests/unit/test_watch_sinks.py`

**Files to edit**
- `src/neowatch/watch/runner.py` — add `run_forever(interval, *, sinks)` with
  graceful cancellation (`asyncio.CancelledError`), per-tick error isolation,
  and optional jitter; thread sinks through `tick()`.

**Steps**
1. `sinks.py`: `AlertSink` (a `Protocol` with `emit(alerts)`); `LogSink`
   (structlog, always on) and `JsonlSink` (delegates to `store.append_alerts`).
2. `runner.run_forever`: `while True: try tick() except Exception: log+continue;
   await asyncio.sleep(interval)`. Catch `CancelledError` to shut down cleanly.
   Sense that the loop must **never die** on a transient error — that's the
   availability property of a watcher.
3. `__main__.py`: argparse for `--once` (single tick, exit code reflects whether
   alerts fired), `--interval SECONDS` (run_forever), `--dry-run` (sense + diff
   but don't persist or emit — for safe inspection). Configure logging like
   `main.py`.
4. Docs: a short "Running the watcher" section in `README.md` + a
   `docs/WATCH_RUNBOOK.md` snippet showing cron, a GitHub Actions `schedule:`
   workflow, and a Claude Code `/schedule` routine all calling `--once`.
5. Tests: `run_forever` cancels cleanly after N ticks (drive with a tiny
   interval + `asyncio.wait_for`/cancel, or inject a fake sleep); a raising
   `tick` is swallowed and the loop continues; sinks receive the right alerts.

**Verification checklist**
- [ ] `python -m neowatch.watch --once` runs a tick and exits; `--interval` loops.
- [ ] A raised exception inside a tick is logged and the loop keeps running.
- [ ] `CancelledError` shuts the loop down without a traceback.
- [ ] Alerts land in `alerts.jsonl`; `--dry-run` writes nothing.
- [ ] `ruff` + `mypy src/` clean; new tests offline and green.

---

### Phase D — Stretch (any subset, each independently valuable)

Not part of the MVP; listed so the "what you'd add next" story is explicit.

- **NEO watcher.** Sense via FetchAgent→CalcAgent (needs NASA key + shared
  Anthropic client). Diff on **object identity**, not a scalar: alert on a
  *newly appearing* close-approach object and on an object whose miss distance
  *tightened* below a lunar-distance threshold. New lesson: set-diffing and
  stable object ids (`neo_reference_id`), plus a `client` in the sense path.
- **LLM digest sink.** A Haiku `MarkdownDigestSink` that turns the deterministic
  alert list into a human paragraph — explicitly *downstream* of the decision,
  never in it. Reuses the shared-client discipline from `pipeline.py`.
- **Watch tab in the UI.** A read-only Gradio tab showing the latest snapshot
  per vertical + recent alerts (read from the store / `alerts.jsonl`). Keeps the
  loop headless-first; the UI is a viewer, not a driver.

---

## 3. Cross-phase definition of done

Same as `PLAN.md` §"Cross-phase definition of done", plus:

1. The loop's alerting decisions are **fully deterministic** — no LLM in the
   decision path (LLM digest, if added, is post-decision only).
2. `tick()` is **idempotent** — proven by a two-tick test per watched vertical.
3. State is **durable and atomic** — no partial-write can corrupt a baseline.
4. The loop is **resilient** — a transient fetch error never kills it.
5. Learning mode honoured: each step narrated *What/Why/Trade-offs/Tools* in
   chat, and a per-phase entry appended to `docs/LEARNING_LOG.md`.

---

## 4. Open decisions (resolve as we build)

- **Cadence granularity.** One global `watch_interval_seconds`, or honour each
  `WatchSpec.cadence_seconds` (Kp updates ~3-hourly; EONET ~daily)? Start
  global; move to per-vertical only if the extra polling is measurably wasteful.
- **State backend.** JSON-file-per-vertical (chosen: simple, inspectable,
  atomic) vs SQLite (better for the `alerts.jsonl` audit growing large). Revisit
  only if the audit trail needs querying.
- **Cooldown / level-triggered reminders.** Deferred by preferring
  edge-triggered rules. Add a per-`key` cooldown in the store only if a real
  "still ongoing" reminder is wanted.
