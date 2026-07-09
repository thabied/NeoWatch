# NeoWatch — Learning Log

A running, plain-English record of what we built, why, the trade-offs, and the
tools involved. Newest entries at the top. This is the durable backup of the
inline chat narration (see the "Learning mode" section in `PLAN.md`).

**Evergreen concept references** (not chronological — kept separate on purpose):
- [`RETRIEVAL_CONCEPTS.md`](RETRIEVAL_CONCEPTS.md) — ranking, re-ranking, cosine
  similarity, dense vs. sparse, hybrid (cascade vs. RRF fusion), ANN/HNSW,
  chunking, and retrieval evaluation — each mapped to NeoWatch's Phase 3 design,
  with what's implemented vs. deliberately skipped and why.

---

## 2026-07-09 — Earth-events vertical: the template pays off (and where the seam bends)

**Why:** The second pluggable domain (Phase 2) — current natural events on Earth (wildfires,
volcanoes, severe storms, floods…) from NASA's keyless EONET feed. The goal this time was
not to prove the seam holds (space weather did that) but to see whether the *second* vertical
is genuinely a fill-in-the-template job. It nearly is: `earth_events.py` and `space_weather.py`
are structurally almost identical. The interesting part is the two places the domain's own
shape pushed back.

**Files:** new `data/eonet.py` (keyless EONET client), `calc/geo.py` (deterministic geospatial
core: haversine, point extraction, active filtering, hotspot), `agents/earth_events_agent.py`
(LLM-free), `domains/earth_events.py` (the `Vertical` + its `contribute`); edits to
`data/models.py`, `calc/models.py`, `domains/registry.py`, `prompts/system_prompts.py`
(orchestrator v3, synthesis v4) and the two agents that import those prompts; new
`tests/unit/test_earth_events.py` (15 tests) + `test_registry.py` count updates. 133 tests green.

### Lessons

- **The second vertical confirmed the template — copy, don't invent.** Building it was
  mechanical: mirror the space-weather files, swap the client/core/tool, append one line to
  `REGISTRY`. The framing agents were again untouched. When the *n*-th instance of a pattern
  looks boring to write, the abstraction is right. The `contribute` hooks now number two, so
  the "exactly one contribution registered" registry test became "exactly two".

- **The dispatch seam has a real limit: agents get `context`, not tool arguments.** I wanted
  "events near <a place the user named>", which needs a reference lat/lon. But the orchestrator's
  `_dispatch` calls every agent as `agent.run(context)` — it never threads the tool call's
  `input` args through. Supporting a parameterised tool would mean editing the dispatch loop,
  i.e. *surgery on the framing layer* — the exact thing the registry exists to avoid. Rather
  than bend the framework for one vertical, I designed the domain to need no arguments. Noted
  for later: if two+ verticals want parameters, that's the signal to generalise dispatch, not
  before.

- **No user reference point? Make the deterministic core relate the data to itself.** Haversine
  needs two points. With no user location, the honest fully-computed product is a *global*
  summary plus a **hotspot found by comparing events to each other**: an O(n²) sweep picks the
  event with the most active neighbours within 500 km. On the live feed this correctly surfaced
  "35 wildfires clustered near the US Four Corners" out of 200 events — a real, useful,
  zero-hallucination figure. Avoiding an LLM-produced reference latitude also kept the core
  honestly deterministic: no model-invented number ever enters a "computed" field.

- **"Empty" is domain-specific — sometimes it's an answer, not a failure.** The space-weather
  agent fails when there's no Kp reading (there's nothing to assess). But zero active Earth
  events is a *valid* result — "all quiet" — so `EarthEventsAgent` returns `success=True` with
  `total_active=0` and a "no significant events" summary. Copying the template blindly would
  have made a calm planet look like a broken API. The only real failure here is not being able
  to *fetch* the feed.

- **GeoJSON coordinates are `[lon, lat]`, and `type` changes the nesting.** Two edge traps the
  live curl exposed before I wrote the parser (Phase 1's "verify live, don't trust the note"
  lesson, applied again): (1) EONET is GeoJSON order — longitude first — so `event_point`
  swaps to return `(lat, lon)`; getting this wrong silently plots everything in the wrong
  hemisphere. (2) A `Point`'s coordinates are `[lon, lat]` but a `Polygon`'s are nested rings
  `[[[lon,lat],…]]`, so I kept `coordinates: list[Any]` raw at the edge and let the core
  descend to the first numeric pair (polygons → first vertex, a representative point). Don't
  over-fit a Pydantic schema to a union-typed field; validate loosely, interpret in the core.

- **Count the *primary* category, not every category.** An EONET event can carry more than one
  category, so tallying them all makes the per-category counts sum to *more* than
  `total_active` — a table that doesn't add up. I count only each event's first category, so
  the breakdown reconciles with the headline number. Small modelling call, but the kind that
  quietly erodes trust in a report if you get it wrong (like Phase 1's choice of a linear
  aurora fit over a lookup table — pick the representation that stays coherent downstream).

- **The whole thing was live-smoked, not just unit-tested.** The 15 unit tests run against a
  hand-built fixture; a hand-built fixture can encode my *assumptions* about the feed. So I
  also ran the real agent against live EONET once — 200 events, real polygons and magnitudes,
  parsed clean, hotspot sane. Fixture tests prove the logic; one live run proves the fixture.

- **A green test suite hid a real bug that only live data revealed: `limit=200`.** During
  end-to-end testing the report said "200 active natural events" — suspiciously *exactly* the
  fetch limit. It was: EONET has ~6832 "open" events (it leaves an event open until a source
  closes it, so a year-old wildfire nobody closed still counts), returned **newest-first**. So
  `limit=200` silently kept only the 200 most-recent events, and every aggregate — the count,
  the category mix, the hotspot — was computed over that biased slice. The unit tests never
  caught it because a 5-event fixture never hits the cap. Two lessons folded into one: (1) when
  a headline number equals a config constant, be suspicious; (2) the fix wasn't "raise the
  limit" — the *semantic* filter is EONET's `days` param: `days=30` returns events with
  activity in the last 30 days (~130), a defensible definition of "happening now", with `limit`
  demoted to a mere safety guard well above that. Pinned with a test that asserts the request
  actually carries `days`. This is precisely what live-smoking is *for*.

---

## 2026-07-07 — Space-weather vertical: the first pluggable domain

**Why:** Phase 0 built the registry seam; this is the first proof it pays off. We added a
whole new science domain — current geomagnetic activity (NOAA planetary Kp index → storm
scale + aurora visibility) — **without touching the orchestrator's dispatch loop or
synthesis's assembly**. The only edits outside the new files are one line in `REGISTRY`,
the guardrail/prompt widening the domain to say "space science" instead of "near-Earth
objects", and the version bumps that widening implies.

**Files:** new `data/noaa_swpc.py` (keyless NOAA client), `calc/space_weather.py`
(deterministic core), `agents/space_weather_agent.py` (LLM-free), `domains/space_weather.py`
(the `Vertical` + its `contribute`); edits to `data/models.py`, `calc/models.py`,
`domains/registry.py`, `prompts/system_prompts.py` (orchestrator v2, synthesis v3) and the
two agents that import those prompts; new `tests/unit/test_space_weather.py` (21 tests) +
`test_registry.py` count updates.

### Lessons

- **The registry earned its keep.** Adding a domain was: write a data client + core + agent,
  declare a `Vertical`, append it to `REGISTRY`. The three framing agents (orchestrator,
  guardrail, synthesis) picked it up with zero changes to their logic — exactly the "config,
  not surgery" promise from Phase 0. The `contribute` hook (dormant while only NEO existed)
  ran for real for the first time.
- **Not every agent needs an LLM.** The litmus test for a domain is "deterministic core, or
  fetch-and-describe?". Space weather has a real core: Kp → NOAA G-scale is a fixed
  threshold table, and the aurora view-line is a near-perfectly-linear fit to SWPC's table
  (66.5° at Kp0 down to 48.1° at Kp9, ~2.04°/Kp). So `SpaceWeatherAgent` makes **no model
  call at all** — it fetches Kp and computes. Cheaper, faster, and impossible to hallucinate
  through. It still implements `BaseAgent`, so the orchestrator dispatches it identically;
  it just accepts-and-ignores the shared Anthropic client the factory hands it.
- **`contribute` keeps the anti-hallucination discipline.** The section, its table rows, the
  grounding block, and the citation are all assembled in Python from the typed
  `SpaceWeatherAssessment` — no LLM prose in the facts. The grounding is *fed to* the
  synthesis model so a pure space-weather query still gets a grounded executive summary, but
  the model only narrates; every number is Python's.
- **A prompt change is a version bump.** Widening the orchestrator's role from "near-Earth
  object" to "space-science" tool (and adding the `assess_space_weather` tool description),
  and letting synthesis discuss non-NEO grounding, are behavioural changes — so
  `orchestrator-v1 → v2` and `synthesis-v2 → v3` per this module's own traceability rule.
  Tests read the version *constant*, not a hard-coded string, so they didn't break.
- **Validate the feed at the edge, keyless.** NOAA SWPC needs no API key and isn't on NASA's
  rate limiter, so the client takes neither `Settings` nor `NasaRateLimiter` — a reminder
  that the shared HTTP layer (timeouts, retries) is reusable independently of the NASA-key
  plumbing.
- **Verify the live shape; don't trust a stale note.** The plan note said the Kp product was
  an "array of arrays" with a header row. The live endpoint is actually an **array of
  objects** (`{"time_tag", "Kp", …}`, newest last). One read-only `curl` before writing the
  parser saved a wrong `KpReading` shape and a fixture that wouldn't mirror production. The
  "newest last" ordering is correctness-critical — it's why `KpIndexReport.latest` is the
  tail, and the offline test pins it (feed `[0.33, 5.67]` → latest `5.67`).
- **Modelling choice: linear fit over a lookup table.** The aurora view-line could have been
  a 10-row Kp→latitude table; instead it's `66.5 − 2.044·Kp`, because SWPC's table *is*
  essentially that line (checked: it reproduces 66.5/60.4/56.3/48.1 at Kp 0/3/5/9 to one
  decimal). A one-line formula with a documented source beats a table to transcribe wrong,
  and it interpolates fractional Kp (readings come in thirds) for free. Clamped to 0–9.
- **Test the new domain offline at every layer.** `test_space_weather.py` exercises all four
  additions without network or an API key: the core via parametrised known values, the
  client parser + fetch via httpx `MockTransport`, the agent end-to-end (success, HTTP
  failure, empty feed) by monkeypatching `get_async_client`, and `contribute` both ways
  (populated blackboard → full block; empty → `None`). Same offline discipline as the NEO
  agents, so the whole vertical stays in the fast unit suite.

---

## 2026-07-02 — Domain registry: generalise the framework, specialise the verticals

**Why:** NeoWatch was hard-wired to near-Earth objects in *three* layers, not one — the
orchestrator's tool list + `if tool_name == …` dispatch, the input guardrail's allow-list,
and the synthesis report's fields (`neo_events`, `orbital_risk_table`). Adding any new
science domain (space weather, Earth events) would have meant editing all three agents.
This is the groundwork (Phase 0) for that expansion: make domains *pluggable* first, then
drop new ones in.

**Files:** new `domains/` package (`base.py`, `neo.py`, `registry.py`, `__init__.py`);
edits to `agents/orchestrator.py`, `agents/synthesis_agent.py`, `guardrails/domain.py`,
`agents/models.py`, `ui/render.py`; new `tests/unit/test_registry.py` + render tests.

### The shape: a `Vertical` is data, not code branches

Each science domain is now declared as a `Vertical` dataclass bundling: its `Capability`
list (one per orchestrator tool — a tool schema + an agent factory + the blackboard
`cache_key` its output is parked under + a `summarise` fn for the planner's status line),
the `topics` that widen the guardrail's allow-list, and an optional `contribute` fn that
adds a report section/grounding/citations. `REGISTRY` is the single source of truth; the
orchestrator, guardrail, and synthesis all *derive* from it via small accessors
(`orchestrator_tools()`, `capability_map()`, `domain_topics()`, `contributions()`).

### Lessons

- **Generalise the framework, specialise the verticals.** The interesting move isn't
  "hit more APIs" — it's making the multi-agent skeleton domain-agnostic so the *next*
  domain is config, not surgery. The registry is that seam. Adding a vertical = append to
  `REGISTRY` + write its data client/agent/core; the three framing agents don't change.
- **Refactor additively on a fact-checked path; don't big-bang it.** The synthesis agent
  is the anti-hallucination core (grounding + post-hoc fact-check). Rather than rewrite it
  around generic sections, NEO keeps its bespoke `neo_events` path (`contribute=None`) and
  *new* verticals render through an additive `report_sections` hook. Net behaviour for NEO
  queries is byte-identical — the whole 89-test suite stayed green through the refactor,
  which is the proof the seam didn't move existing behaviour.
- **Preserve injection seams when you move construction.** The orchestrator used to build
  its four agents inline; tests inject stubs via `fetch_agent=/calc_agent=/…`. The default
  set now comes from `capability_map()`, but a name-keyed override map keeps that
  constructor API intact — so the refactor is invisible to every existing test.
- **Watch for import cycles when a low layer becomes a hub.** The registry imports the
  agent classes (to build them), and the orchestrator/guardrail/synthesis import the
  registry. Splitting the dataclasses into `domains/base.py` (no registry import) from
  `domains/registry.py` (assembles concrete verticals) keeps `neo.py` free to import
  `base` without a cycle back through `registry`.
- **Deterministic sections keep the discipline.** `ReportSection.body_markdown`/`rows` are
  built in Python from a vertical's computed core, not LLM prose — same "model writes
  prose, Python assembles facts" rule as the NEO path. The `grounding` field lets a
  vertical still feed the executive-summary model so a non-NEO query gets a grounded
  overview. (Extending the *numeric fact-check* to new domains is deferred — noted for the
  vertical PRs that add real figures.)

## 2026-06-29 — Tier 3 implemented: early-stop logs, topic imagery, parse guard

**Files:** `agents/fetch_agent.py`, `agents/orchestrator.py`, `agents/synthesis_agent.py`,
`agents/image_agent.py`, `data/images.py` (new), `data/models.py`, plus tests. Backlog
items #5, #6, #7 from [`IMPROVEMENTS.md`](IMPROVEMENTS.md).

### #5 — Don't swallow non-`tool_use` stop reasons

Both tool-use loops did `if resp.stop_reason != "tool_use": break`. `end_turn` is the
normal exit, but `max_tokens` (Haiku's 1024 cap; Sonnet's 2048) and `refusal` mean the
model was cut off or declined *mid-plan* — and we'd then assemble a report from partial
data with no trace of why. Added a `self.logger.warning(...early_stop, stop_reason=...)`
on exactly those two reasons before the break, in both loops.

**Lesson — a silent `break` hides a whole failure class.** The fix is one line, but the
value is observability: a truncated fetch or a refused plan now leaves a log line
instead of a mysteriously thin report. Tested with `structlog.testing.capture_logs()`,
which captures structured events regardless of which bound logger emitted them — so the
assertion is on the event name + `stop_reason` field, not on formatted text.

### #6 — Topic-relevant imagery (search-first, APOD fallback)

**The problem.** `ImageAgent` only fetched APOD *by date range*, so "an image of
Apophis" returned whatever the Astronomy Picture of the Day was that window — never a
subject match. **The fix** adds a new `data/images.py` client over NASA's Image & Video
Library (`images-api.nasa.gov` — a *keyless* host, separate from the rate-limited
`api.nasa.gov`), and reshapes `ImageAgent.run` into **search-first with APOD fallback**:
1. Reduce the query to its topic by stripping imagery filler words
   (`show / me / an / image / of …`). If nothing survives, there's no topic → skip search.
2. Search the Image Library on those terms; prepare any hits.
3. If the search yields nothing usable (no topic, or zero results), fall back to the
   always-available APOD-by-date path.

**Lessons:**
- **Degrade to the always-available source, not to nothing.** The teaching shape is the
  fallback: prefer the topical source, but never return an empty gallery when a generic
  one exists. The two sources feed one shared download→validate→resize→`ImageAsset` core,
  so only the *fetch* differs.
- **Parse heterogeneous search results defensively.** The library response is deeply
  nested (`collection.items[].data[0]` for metadata, `.links[0].href` for the preview)
  and rows vary — videos, items missing a preview link. `parse_image_search` *skips*
  anything unusable rather than raising, so one odd result can't sink the batch.
- **A keyword strip is a deliberately dumb heuristic.** No LLM call to extract the topic
  (this agent is LLM-free by design) — a stopword filter is good enough and explainable,
  and the empty-result fallback covers the cases where it's too aggressive.
- **The existing tests kept passing for free:** their queries ("show me images",
  "images") are pure filler, so they reduce to an empty topic and take the APOD path
  exactly as before. Search only fires when a real subject is present.

### #7 — Synthesis parse-failure guard

Tier 1 already handled `parsed_output is None` (refusal/truncation). The remaining gap:
if `messages.parse` itself *raises* (SDK validation, transport), it propagated out of
`SynthesisAgent.run` — and since synthesis is the **last** stage, that breaks the
pipeline's "always return a `FinalReport`" contract. Wrapped the call so any exception
logs `synthesis.parse_failed` and degrades to empty prose; the computed tables/citations
still build. `FakeResponse` gained a `raises` field so a test can simulate the throw.

**Lesson — the contract holds only if the last stage can't throw.** Every earlier agent
already "returns failure as data"; synthesis now matches, so no single call can turn a
valid run into an unhandled exception at the UI.

**Verification:** `ruff` clean, `mypy src/` clean (50 files), **89 tests pass**.

---

## 2026-06-29 — Tier 2 implemented: split token counters + one shared client

**Files:** `context.py`, `guardrails/token_budget.py`, `pipeline.py`, plus the five
`add_tokens` call sites (`orchestrator.py`, `fetch_agent.py`, `synthesis_agent.py`,
`calc_agent.py`, `guardrails/domain.py`) and tests. Backlog items #3 and #4 from
[`IMPROVEMENTS.md`](IMPROVEMENTS.md).

### #3 — One counter was measuring two different things

**The bug.** `AgentContext.tokens_used` accumulated *cumulative billed cost*
(input + output, every call). But `TokenBudgetGuardrail._compress` re-baselined it
to `_estimate_tokens(history)` — a char-estimate of the *current* history size.
After the first compression the same number silently changed meaning: the 95% hard
stop was now comparing a footprint estimate against a cost budget. A counter that
means two things means nothing.

**The fix — two counters, each watched by the decision that owns it.**
- `cost_tokens`: **monotonic** cumulative bill (input + output). You can't un-spend
  money, so it only grows. The **hard stop** (95%) and **warn** (70%) watch this.
- `context_tokens`: the live context-window footprint — set to the *last call's
  input tokens* (literally the size of the conversation we just sent). **Compression**
  (85%) watches this.

**Why each decision uses the counter it does** (the real insight):
- Compress keys off `context_tokens` because compression is the *only* lever that
  moves it. If compress were keyed off cost (which compression can't lower), it would
  re-fire on every check forever — which is exactly why the old code re-baselined the
  counter, papering over the design flaw with a meaning-switch.
- Stop keys off `cost_tokens` because the bill is the thing you genuinely cannot walk
  back, so that's what a hard halt must protect.

**`add_tokens` now takes `(input_tokens, output_tokens)`** instead of a pre-summed
count: `cost_tokens += input + output`, `context_tokens = input`. Using the real
`input_tokens` as the footprint (the doc's "summed `resp.usage`" suggestion) is more
accurate than the char-estimate and makes `context_tokens` meaningful in the live
orchestrator/fetch loops — whose growing message history shows up as rising input
tokens. (`_estimate_tokens` survives for exactly one spot: setting `context_tokens`
right after a local compress, before the next real call gives us an exact count.)

**Scope note I had to resist.** `context.history` is only ever populated by tests —
production agents drive local `messages` lists — so the compression machinery is
*dormant* in production today. Wiring history through is a separate change; #3 is
purely about the counter semantics, so I left that alone.

**Regression test:** `test_compression_lowers_footprint_not_the_bill` asserts that
after a compress, `context_tokens` drops but `cost_tokens` grew by the summary call's
own usage and was never reset — the exact behaviour the old single counter got wrong.

### #4 — One Anthropic client per run, closed at the end

**The leak.** Each agent did `self.client or get_anthropic_client(self.settings)`, so
in production (no injected client) every agent and guardrail built its *own*
`AsyncAnthropic` — each with its own HTTP connection pool — and **none were closed**.
That's a pool leak per agent per request.

**The fix.** `run_query` now builds **one** client and threads it through both stages
(they already pass it down to every sub-agent and guardrail). The lifecycle rule is
ownership-based:
```python
owns_client = client is None
client = client or get_anthropic_client(settings)
try:
    ...  # orchestrator + synthesis, both with client=client
finally:
    if owns_client:
        await client.close()
```
We close only a client we created. A caller-injected client (a test's
`FakeAnthropic`, or a future long-lived shared client) is the caller's to manage —
closing it from here would be a surprise.

**Two SDK details worth recording:**
- The async client's method is `await client.close()`, **not** `aclose()` (I checked
  `hasattr` before writing rather than guessing — `AsyncAnthropic` has `close`, no
  `aclose`). It also supports `async with`, but the explicit try/finally reads clearer
  with the create-or-inject branch.
- Tests verify both arms: `FakeAnthropic` grew a `close()` that flips a `closed` flag;
  one test patches `get_anthropic_client` so the owned-client path runs offline and
  asserts `closed is True`, another injects a client and asserts `closed is False`.

**Verification:** `ruff` clean, `mypy src/` clean (49 files), **81 tests pass**.

---

## 2026-06-29 — Tier 1 implemented: structured outputs + prompt caching

**Files:** `agents/synthesis_agent.py`, `agents/fetch_agent.py`,
`prompts/system_prompts.py`, `tests/unit/fakes.py`, `tests/unit/test_synthesis_agent.py`.

This turned the two top backlog items from [`IMPROVEMENTS.md`](IMPROVEMENTS.md) into
code. The *lessons* from 2026-06-27 predicted the wins; this entry records how they
played out in practice and the few things that only become clear once you write it.

### #1 — Structured outputs replace the regex (synthesis)

**What.** Sonnet's prose is now requested with `client.messages.parse(...,
output_format=ProseModel)` instead of `messages.create` + a greedy `\{.*\}` regex +
`json.loads`. `ProseModel` is a Pydantic model (`executive_summary`,
`literature_insights`, `event_summaries: list[EventSummary]`); the SDK turns it into a
JSON schema the API enforces and hands back a validated object on `resp.parsed_output`.
The `_JSON_RE` constant and `_parse_prose` method are gone.

**Why it matters concretely.** The old failure was *silent*: any stray brace in the
model's surrounding prose made the regex over-match, `json.loads` threw, and the report
came back **empty with no error**. The new regression test
`test_brace_laden_prose_yields_populated_report` feeds prose stuffed with literal braces
(`"Risk set {Torino 0}…"`, `"A routine flyby {low risk}."`) and asserts they survive
*verbatim* into the report — exactly the input that used to zero it out.

**Trade-offs / things learned.**
- `parsed_output` can still be `None` — on a refusal or a `max_tokens` truncation the
  API returns no complete object. So I kept a graceful degrade:
  `resp.parsed_output or ProseModel(empty)`. The deterministic tables/citations still
  build; you lose only the prose. "Degrade, don't crash" survives the rewrite.
- **The schema is now the contract, so the prompt shouldn't also describe it.** I
  dropped the "respond with JSON" framing from the system prompt — describing the shape
  in prose *and* enforcing it by schema is redundant and can even conflict. By the
  project's own rule (a behaviour-changing prompt edit = a new version) this bumped
  `SYNTHESIS_V1 → SYNTHESIS_V2` / `synthesis-v2`, so every report stays traceable to the
  prompt that made it. (Note: `IMPROVEMENTS.md` called it `SYNTHESIS_V1`; the version
  bump is the faithful application of our own versioning rule.)
- `temperature` is still valid alongside `output_format` on Sonnet 4.6, so we keep a
  little warmth (0.4) for readable prose while the *shape* is hard-constrained.

### #2 — Prompt caching on the FetchAgent loop

**What.** Added `cache_control={"type": "ephemeral"}` to the Haiku `messages.create`
call inside the tool-use loop. This is *top-level auto-caching*: the SDK marks the last
cacheable block (the growing message history) as an ephemeral breakpoint, so each
iteration after the first re-reads the accumulated NASA tool results at ~0.1× instead of
full input price.

**Why here and nowhere else.** This is the 2026-06-27 lesson made literal: caching only
fires above the model's minimum cacheable prefix (Haiku 4.5 = 4096 tokens). FetchAgent's
history carries ~4.8k tokens of raw tool results — *above* the floor, so it pays off.
The orchestrator loop carries only tiny status strings — *below* the floor — so we
deliberately did **not** cache it (it'd be a no-op). Optimise where the tokens actually
are.

**How to verify it's live.** On a real run, check `resp.usage.cache_read_input_tokens >
0` on the 2nd+ iterations. (The offline suite can't see this — `FakeAnthropic` doesn't
model cache accounting — so this is a live-run check, noted in the code comment.)

### Testing notes (offline, zero paid calls)
- `FakeAnthropic` grew a `parse()` method (shares the response queue with `create()`)
  and `FakeResponse` grew a `parsed_output` field — so tests inject a ready-made
  `ProseModel` exactly where the real SDK would put the validated object.
- New/changed tests: the brace regression test above, plus
  `test_missing_parsed_output_does_not_crash` (feeds `parsed_output=None`,
  `stop_reason="refusal"`, asserts empty summary but tables still built).
- **Both new params are typed in SDK 0.111.0** (`parse(output_format=)` and
  `create(cache_control=)`), so `mypy --strict` needs no `# type: ignore`. I checked the
  SDK source for this before writing code rather than guessing — and confirmed the
  attribute is `parsed_output` (a property), not `.parsed`.

**Verification:** `ruff` clean, `mypy src/` clean (49 files), **78 tests pass**
(`pytest tests/unit tests/integration/test_smoke.py`).

---

## 2026-06-27 — Architecture review: improvement findings + a Claude Code lesson

No code changed today — this was a full read-through of the system to find what to
improve next. The actionable backlog lives in [`IMPROVEMENTS.md`](IMPROVEMENTS.md);
this entry captures the *lessons*, which are the durable part.

### What the review confirmed (the good)
The deterministic-core / LLM-shell discipline is consistent everywhere, and it has a
cost consequence worth naming: **large payloads never enter the model context.** NEO
data, papers, and images are parked on the `session_cache` blackboard; only short
status strings ("Fetched 10 close-approach objects.") flow through the orchestrator's
LLM loop. That's why several "obvious" token optimisations don't apply here — the
architecture already starves the LLM of tokens by design. The one exception is
`FetchAgent`, whose Haiku loop *does* carry the raw NASA tool results in its message
history (this is what spent ~4.8k tokens and caused the budget bug).

### Three lessons for later
1. **Structured outputs beat regex parsing of LLM JSON.** `synthesis_agent.py` asks
   Sonnet for JSON and scrapes it with a greedy `\{.*\}` regex. If the model wraps the
   JSON in any prose containing braces, the parse silently yields `{}` → an empty
   report, no error. The SDK's `messages.parse(output_format=PydanticModel)` (Sonnet
   4.6 supports it) *guarantees* schema-valid output. Lesson: when you need JSON from a
   model, constrain it at the API, don't pattern-match the text afterwards.
2. **Prompt caching pays off exactly where tokens accumulate — not everywhere.**
   Adding `cache_control` to an agentic loop lets later iterations re-read earlier turns
   at ~0.1×. But it only fires above a model's minimum cacheable prefix (Haiku 4.5:
   4096 tokens). The orchestrator loop is *below* that (status strings are tiny), so
   caching it is a near-no-op; FetchAgent is *above* it, so that's where to cache.
   Lesson: measure where the tokens actually are before optimising — here the
   architecture's own frugality concentrates the win in one place.
3. **A "token budget" must mean one thing.** `context.tokens_used` accumulates
   *cumulative billed cost* (input+output every call), but the compression path
   re-baselines it to a *char-estimate of current history size* — silently switching
   the number's meaning mid-run, which is how the original mis-scoping hid. Lesson:
   cost-budget and context-footprint are two different quantities; track them
   separately rather than overloading one counter.

### The meta-lesson: manage context by task boundary, not by clock
We decided to move the implementation work to a **fresh conversation** rather than
continue this one. The reasoning is a reusable Claude Code heuristic: **start fresh
when the next task doesn't need the specific working context you've accumulated, and
what it *does* need is already on disk.** This session had loaded the entire Claude API
reference (huge) for the review — dead weight for implementation — while everything the
next task needs is in the repo + this log + `IMPROVEMENTS.md`. The durable memory of a
Claude Code project is the filesystem (code, learning log, memory files), not the chat;
scoping conversations to coherent tasks keeps both cost and fidelity high.

---

## 2026-06-25 — Gallery fix: Gradio won't serve un-allowed local files

**Files:** `config.py`, `agents/image_agent.py`, `main.py`, `app.py`, `.gitignore`.

### What
The image gallery rendered **blank** in the browser even though the image agent
had downloaded and resized the APOD file and set `local_path` correctly. Fix:
make `local_path` absolute and pass `allowed_paths=[<image cache dir>]` to every
`launch()` call. Added an `image_cache_dir` setting as the single source of truth
and gitignored `.image_cache/` (it was missing from `.gitignore`, only in
`.dockerignore`).

### Why it happened
Since Gradio 4 (we're on 6.19), the dev server **refuses to serve arbitrary local
files** for security — the working directory is no longer auto-served. A component
handed a filepath outside the allow-list produces an `<img>` whose request the
server denies, so the picture is silently blank. The file existed, the path was
valid, and the server still wouldn't hand it over. `allowed_paths` is the
documented way to permit a directory; an absolute path avoids the server resolving
the relative path against its own cwd.

### The lesson (again)
**Headless/programmatic runs hide rendering bugs.** Both earlier "successful" live
runs produced a valid `ImageAsset` with a path — green all the way — but nothing
ever asked a *browser* to fetch that path. Same shape as the token-budget bug:
fakes and non-visual runs pass while the real UX is broken. A human looking at the
actual page is still an irreplaceable test.

### Subtlety worth remembering
A separate red herring surfaced first: a plain risk query ("…how risky are
they?") sometimes shows no image simply because the orchestrator **chose not to
call** `fetch_images` (LLM planning variance at `temperature=0.2`). "No image" had
two independent causes — one a real serving bug, one expected planner behaviour.
Diagnosing meant separating them: the server-side file check (HTTP 200) proved
serving worked, and the `orchestrator.done invoked=[…]` log proved the agent
wasn't called. To reliably exercise imagery, the query must *ask* for it.

---

## 2026-06-24 — Phase 8 (Production hardening) — COMPLETE

**Files:** `Dockerfile`, `.dockerignore`, `app.py` (repo root, HF Spaces entry),
`README.md`, `.github/workflows/ci.yml`, `tests/conftest.py`,
`tests/integration/test_smoke.py`, `docs/DEMO.md`.

### What
The shipping layer: a `Dockerfile`, a HuggingFace Spaces entry point, a real
`README`, CI, shared test fixtures, an offline smoke test, and a demo placeholder.
Nothing about the system's behaviour changed — this phase makes it *deployable and
legible to a stranger*.

### Why
A project that only runs on the author's laptop isn't finished. Phase 8 answers
"how does someone else run this?" — clone → keys → `docker build` / `Spaces` →
working UI — and gives the repo a front page that explains the engineering ideas.

### Key lessons
- **A README is part of the product.** The architecture diagram, the env-var table,
  and the run/test/deploy commands are what turn a pile of modules into something
  another person can use. Writing it also pressure-tests the design: the
  `FinalReport` schema mapped cleanly onto the UI, which is evidence the contract
  was right.
- **Layer caching in Docker.** Copy `requirements.txt` and `pip install` *before*
  copying `src/`, so a code-only change doesn't re-download chromadb/gradio every
  build. Ordering Dockerfile steps from least- to most-frequently-changed is the
  whole trick.
- **No persistence assumed.** The Chroma vector store is re-ingested on first run,
  so the container needs no volume — and `.dockerignore` excludes `.chroma/`,
  `.env`, `.venv`, and `tests/` to keep the build context small and secret-free.
- **Shared fixtures (`conftest.py`).** The repeated "set test env vars + clear the
  settings cache" dance and a canned `FinalReport` now live in one place, so new
  tests stay short. pytest discovers `conftest.py` automatically.
- **Two kinds of "end-to-end".** `test_smoke.py` is an *offline* end-to-end
  (run_query → render via a fake client, zero cost) that CI runs on every push;
  `test_end_to_end.py` is the *live* one, gated behind `NEOWATCH_RUN_INTEGRATION`.
  Cheap wiring-checks run always; expensive truth-checks run on demand.

### Gotchas / honest notes
- **Base image deviation:** the spec said `python:3.11-slim`, but the code requires
  3.12 (`requires-python`, numpy 2.x). Used `3.12-slim` and documented why — matching
  the spec literally would have produced a broken image.
- **onnxruntime needs `libgomp1`** in slim images; added it via apt.
- **Docker build not run this session** — the local Docker daemon was down, and I
  won't auto-launch a GUI app. The Dockerfile is standard and reviewed; one
  `docker build -t neowatch .` ticks the last box. (I declined to fake a "verified"
  here — it's marked pending, not done.)
- The **demo GIF/screenshots** need a live keyed run in a browser; `docs/DEMO.md`
  holds the capture steps and the slots, honestly marked as a placeholder.

### Verification
`ruff` clean · `mypy src/` clean (49 files) · **76/76** non-integration tests
(unit + offline smoke). CI workflow runs the same three gates on every push.

### Live-run findings (2026-06-24) — two bugs only a real run could surface
- **Mis-scoped token budget (real bug, fixed).** The orchestrator wired its
  `TokenBudgetGuardrail` to `max_tokens_per_agent` (4096), but it watches the
  *cumulative* context across all agents. A live run showed FetchAgent alone spends
  ~4.8k tokens carrying NEO data, so the loop hard-stopped after one agent and the
  report came back empty. Fixed to use `token_budget_per_session` (200k); added a
  regression test. The offline suite missed this because `FakeAnthropic` reports
  only 15 tokens/call — a reminder that fakes hide magnitude bugs, and that a single
  live run is worth a lot of green offline tests.
- **Docker `--env-file` ≠ dotenv (deploy gotcha).** Docker's env-file parser keeps
  inline `# comments` as part of the value, so int settings failed to parse and the
  container crashed on boot. Fix: *mount* `.env` and let pydantic-settings parse it.
- **What worked, live:** real NASA data → 10 asteroids with computed figures →
  Sonnet narrative that the fact-check passed at "high" confidence; the orchestrator
  correctly invoked only fetch+calc (not literature/images) for a risk query. The
  deterministic-core/LLM-shell held up against real data.

### Project status: all 8 phases complete
NeoWatch is functionally and structurally done end-to-end — guarded input →
agentic orchestration → deterministic computation + RAG → grounded, fact-checked
report → web UI → container/Spaces deploy. Remaining manual ticks: a real
`docker build` and the demo capture (both need only a running daemon / API keys).

---

## 2026-06-24 — Phase 7 (Gradio UI) — COMPLETE

**Files:** `src/neowatch/ui/{render,app}.py`; `src/neowatch/main.py` (launches the
UI); `src/neowatch/context.py` (`ProgressCallback`); `pipeline.py` +
`agents/{orchestrator,synthesis_agent}.py` (progress hook); `tests/unit/test_render.py`.

### What
The first phase you can *click*. A Gradio `Blocks` app: a query box, a risk
dataframe, a markdown report pane, and an image gallery. Submitting a query runs
`pipeline.run_query` and streams per-agent progress, then renders the `FinalReport`.

### Why
Everything before this was code and tests; Phase 7 makes it a product a person can
use. It also forces the report schema to prove itself — if `FinalReport` were
awkward to display, we'd feel it here. (It wasn't: pure renderers map it straight
onto widgets.)

### Key lessons
- **Pure renderers vs. the framework shell.** `ui/render.py` turns a `FinalReport`
  into a markdown string, a pandas DataFrame, and a gallery list — all *pure
  functions with no Gradio imports*. So they unit-test without launching a server
  (4 fast tests). `app.py` is the only module that touches Gradio. Same separation
  lesson as deterministic-core/LLM-shell, applied to UI: keep the testable logic
  away from the hard-to-test framework boundary.
- **Streaming over a single `await` (producer/consumer).** `run_query` is one long
  coroutine — the UI can't peek inside it. The fix: run the pipeline as a background
  `asyncio.create_task`, and have it push status strings onto an `asyncio.Queue`
  (via an optional `progress` callback threaded down to the orchestrator). The
  Gradio handler is an *async generator* that drains the queue, yielding a UI
  update per message, then yields the finished report last. This is the standard
  way to get progress out of an opaque async call.
- **Optional hooks keep layers decoupled.** The `progress` callback is `None`
  everywhere by default, so the pipeline stays headless and testable; only the UI
  passes a real callback. The front-end depends on the pipeline, never the reverse.
- **Degrade in the UI too.** The handler wraps the run in try/except and shows
  errors in the status pane; an off-topic query renders the guardrail's rejection
  `FinalReport` like any other report. No traceback ever reaches the user.

### Gotchas
- **mypy + third-party types.** pandas needs `pandas-stubs`; gradio *is* typed but
  its `with gr.Blocks() as demo` yields `Any`. Added `pandas.*`/`gradio.*` to the
  mypy `ignore_missing_imports` override, and `cast`-ed the `Blocks` return so
  `--strict` stays honest without weakening checks on our own code.
- Gradio installed as **6.19** (newer than the plan's 4.36); the `Blocks` /
  `Dataframe` / `Gallery` API used here is stable across that gap.

### Verification
`ruff` clean · `mypy src/` clean (49 files) · **75/75 unit tests** (+4). Launched
the server for real: `build_app().launch(server_port=7860)` serves **HTTP 200** on
`/`. A full live query (real report in the browser) needs API keys — a manual check.

---

## 2026-06-24 — Phase 6 (Orchestrator and synthesis) — COMPLETE

**Files:** `src/neowatch/prompts/system_prompts.py`;
`src/neowatch/agents/{orchestrator,synthesis_agent}.py`;
`src/neowatch/agents/models.py` (FinalReport / NEOEventReport / RiskTableRow /
Citation); `src/neowatch/pipeline.py`;
`tests/unit/{test_orchestrator,test_synthesis_agent,test_pipeline}.py`;
`tests/integration/test_end_to_end.py`.

### What
The capstone that connects everything. The **OrchestratorAgent** (Sonnet) runs the
domain guardrail, then drives a tool-use loop where each specialist agent (fetch,
calc, RAG, image) is a Claude *tool* it can choose to call. The **SynthesisAgent**
(Sonnet) turns the collected outputs into a single validated `FinalReport`, then
fact-checks it. `pipeline.run_query(query)` is the one entry point the UI will call.

### Why
Phases 4-5 built capable, safe *parts*; Phase 6 makes them a *system*. The
orchestrator is the "agentic" core — the LLM decides the plan (which agents, in
what order) instead of running a fixed script. That's the headline lesson of the
whole project: tool use lets a model *act*, not just talk.

### Key lessons
- **Agents-as-tools (the agentic loop, one level up).** Phase 4 used tool use so
  Haiku could call *NASA APIs*; here Sonnet uses tool use to call *other agents*.
  Same mechanism (tool schemas → `tool_use` blocks → execute → `tool_result` →
  loop), one level of abstraction higher. A query about "this week's asteroids"
  calls fetch+calc; a query about "detection research" calls literature — the plan
  is data-dependent, and a test proves only the needed agents run.
- **The cost/agency trade-off, made explicit.** A real tool-use loop spends Sonnet
  tokens *planning* that a hard-coded `fetch→calc→synthesise` sequence wouldn't. We
  chose the agentic loop (it's the lesson) but bounded it: a 6-iteration cap, a
  budget check between every step, and empty tool-input schemas so Sonnet decides
  *whether* to call, not fiddly arguments. Naming the trade-off out loud is the
  point — "agentic" is not free.
- **Deterministic core, all the way to the report.** Same pattern as CalcAgent, now
  in synthesis: Sonnet writes *only prose* (summary, insights, one line per event);
  every number, table row, and citation is assembled in Python from the computed
  figures. So `FactCheckLayer` audits exactly what the model wrote, and a
  hallucinated "99 LD" can only ever surface as a flagged confidence note — it can
  never reach the risk table. Verified by a test.
- **The shared blackboard.** Agents don't call each other; the orchestrator parks
  each output on `context.session_cache` under known keys (`neo_data`,
  `orbital_report`, `papers`, `images`) and synthesis reads from there. Loose
  coupling: any agent can be swapped without the others knowing.
- **Degrade, don't crash.** The model's prose JSON is parsed best-effort — a
  non-JSON reply yields empty prose, not an exception, and the deterministic tables
  still build. A guardrail rejection becomes a valid (empty) `FinalReport` carrying
  the reason, so the UI never special-cases errors.

### Gotchas
- A stray CJK character ("近") slipped into a prompt string while typing; caught on
  review. Worth a `git diff` read-through on hand-authored prose.
- Offline-testing a multi-LLM pipeline needs care: the orchestrator's Sonnet loop
  and the domain guardrail share one injected client, so the `FakeAnthropic`
  response *sequence* must match call order (domain check first, then plan steps).
  Specialist agents are injected as stubs so their own LLM calls don't consume that
  sequence — keeping each test's fake responses readable.

### Verification
`ruff` clean · `mypy src/` clean (49 files) · **71/71 unit tests** (+6), all offline
via `FakeAnthropic`. The full live run is `tests/integration/test_end_to_end.py`
(gated by `NEOWATCH_RUN_INTEGRATION=1`; spends real tokens, hits NASA/arXiv).

---

## 2026-06-24 — Phase 5 (Guardrails and safety) — COMPLETE

**Files:** `src/neowatch/guardrails/{models,sanitise,domain,factcheck,token_budget}.py`;
`src/neowatch/context.py` (compress_history); `src/neowatch/guardrails/__init__.py`;
`tests/unit/{test_domain_guardrail,test_factcheck,test_token_budget}.py`;
updated `tests/unit/test_context.py`.

### What
Three protective layers around the agents. **Input** — `DomainGuardrail.validate`
runs four checks cheapest-first (length → injection → harm → a Haiku YES/NO domain
classification) and rejects bad queries before the pipeline spends anything.
**Output** — `FactCheckLayer` extracts `<number> <unit>` claims from generated prose
and flags any that don't match the trusted computed figures within 5%. **Budget** —
`TokenBudgetGuardrail` warns at 70%, compresses history at 85% (Haiku summarises old
turns), hard-stops at 95%.

### Why
Phase 4 made the system *reason*; Phase 5 makes it *trustworthy and affordable*.
Each layer maps to a real risk: off-topic/malicious input (waste + abuse),
hallucinated numbers (the classic LLM failure), and runaway context (cost). These
are the difference between a demo and something you'd let touch a budget.

### Key lessons
- **Fail fast and cheap.** The three free checks (pure Python/regex) gate the one
  paid check (Haiku domain classifier), which gates the whole expensive pipeline.
  A pizza-recipe query or an injection string is rejected for *zero* tokens — a test
  asserts `fake.messages.calls == 0` to prove the model was never consulted.
- **Anti-hallucination by verification, matched *by unit*.** We don't trust the
  model's numbers; we check them against figures we computed ourselves. The subtle
  bit: a hallucinated `18 LD` sits right next to a real `18.1 km/s`, so matching to
  the "nearest number overall" would wave it through. Pinning each claim to its unit
  (LD vs km/s) keeps the check honest. Claims are *flagged, never deleted* —
  confidence is surfaced to the user, not silently rewritten.
- **Keep the LLM out of the data model.** Compression needs a summary (an LLM call)
  *and* a structural rewrite. We split them: the guardrail owns the paid Haiku call;
  `AgentContext.compress_history(summary)` takes the finished summary and does a pure
  list rewrite. Result: the context model has zero Anthropic dependency and is
  trivially unit-testable, while the paid call stays in the guardrail where the
  budget logic lives.
- **Layered, not airtight.** `detect_injection` is a heuristic that catches known
  phrasings, not a proof. Combined with the domain classifier and the output
  fact-check, it *raises the cost of an attack* without pretending to be unbreakable
  — the honest framing for security work.

### Gotchas
- A Phase 1 test asserted `compress_history` raised `NotImplementedError`; finishing
  the feature meant updating that test (a healthy sign the contract was real from the
  start, not invented late).
- The verification checklist's "compression reduces `tokens_used`" forced a decision:
  `tokens_used` is re-baselined to the *compressed* footprint after summarising,
  modelling current-context occupancy (what the next call will carry), not a
  monotonic lifetime counter.
- Step 6 ("mask emails in logs") was already satisfied — `strip_secrets` (Phase 1)
  always carried the email regex. Verified by a regression test rather than rebuilt.

### Verification
`ruff` clean · `mypy src/` clean (49 files) · **65/65 unit tests** (+18 this phase),
all offline via `FakeAnthropic` — zero paid API calls.

---

## 2026-06-23 — Phase 4 (Agent system) — COMPLETE

**Files:** `src/neowatch/calc/{models,orbital}.py`;
`src/neowatch/tools/{schemas,fetch_tools}.py`; `src/neowatch/llm.py`;
`src/neowatch/agents/{models,fetch_agent,calc_agent,image_agent,rag_agent}.py`;
`tests/unit/{fakes,test_calc_orbital,test_calc_agent,test_fetch_agent,test_image_agent,test_rag_agent}.py`.

### What
Built the four specialist agents — the first phase that calls Claude. **FetchAgent**
drives a Haiku tool-use loop over the Phase 2 NASA clients; **CalcAgent** computes
orbital/risk figures in pure code and uses Haiku *only* to narrate them;
**ImageAgent** fetches/validates/resizes APOD images (no LLM); **RAGAgent** wraps
the Phase 3 `retrieve()` (no LLM). All subclass `BaseAgent` → `AgentResult`.

### Why
This is where the system stops being plumbing and starts *reasoning*. The
orchestrator (Phase 6) will call these as interchangeable units. Splitting them by
job keeps each one small, cheap, and independently testable.

### The headline AI-engineering lesson: deterministic core, LLM shell
The most important pattern in the whole project lives in CalcAgent: **the LLM never
produces a fact or a number.** Risk and orbital figures are computed in pure
numpy/`calc/orbital.py`; Haiku is handed the finished numbers and asked only to
phrase them. A test asserts `report.analyses[0] == analyse_orbit(...)` *field for
field*, so any drift is caught. This is exactly what the Phase 5 fact-check layer
will verify, and it's why we can trust the output: facts come from code we can
unit-test, language comes from the model.

### Model routing & cost discipline
- **Haiku 4.5** for all specialist agents (the spec's cheap-model tier). Haiku
  takes no `thinking`/`effort` params (those are Opus-tier) — keep calls plain.
- Every agent takes an **injectable Anthropic client**, so the whole unit suite
  runs against a `FakeAnthropic` (`tests/unit/fakes.py`) with **zero paid calls**.
  This is the cost guardrail in practice: you must be able to test agent logic
  without spending tokens. NASA/APOD HTTP is faked with httpx `MockTransport`.

### Key concepts & tools introduced
- **Tool use (the agentic loop)** — we pass JSON-schema tool definitions to Claude;
  it replies with `tool_use` blocks; we execute the matching Python and feed
  `tool_result` back, looping until `stop_reason != "tool_use"`. The model *decides
  which data to fetch*; Python *executes* it against typed clients.
- **Two consumers, two shapes** — Haiku sees a compact text summary of each tool
  result (`to_tool_result_text`, token-bounded) while the agent keeps the full
  typed object to assemble `NEOData`. Don't pay tokens for data the model won't read.
- **Chunking rule** — sort the feed by miss distance, enumerate the 10 closest,
  fold the rest into a `remainder_count`. Bounds prompt size on busy days.
- **Manual loop vs. SDK tool-runner** — chose the manual loop for control: it lets
  us capture typed models, dedupe via `session_cache`, and feed tool errors back
  as `is_error` results so Haiku can recover.

### Gotchas hit
- **mypy caught a real bug pre-runtime:** I wrote `is_potentially_hazardous`; the
  field is `is_potentially_hazardous_asteroid`. `--strict` flagged it in three
  files before a single test ran — the payoff of strict typing.
- **SDK TypedDict friction:** the Anthropic SDK types `tools`/`messages` as strict
  TypedDicts; our hand-built JSON-schema dicts (with `additionalProperties`, etc.)
  don't match. Resolved with a `cast` at the `messages.create` boundary, with a
  comment — a legitimate, localized escape hatch.
- **z-score self-masking:** a single large outlier inflates its *own* standard
  deviation on small samples, so `|x−mean| > 2σ` can miss it. The anomaly test uses
  a large, tight cluster so the outlier stays detectable — a real statistics trap.
- **Pillow was missing** (torch's removal in Phase 3 freed numpy 2.x, but Pillow
  was never installed); added it. Image resize/attribution is pure I/O, no LLM.

### Verification
`ruff` clean · `mypy --strict` clean (49 files) · **47/47 unit tests** (+22 this
phase, all offline/no-cost). Live agent runs land in the Phase 6 end-to-end test.

---

## 2026-06-22 — Phase 3 (RAG pipeline) — COMPLETE

**Files:** `src/neowatch/rag/{models,embed,chunk,store,ingest,retrieve}.py`;
`tests/unit/{test_chunk,test_retrieve,test_store}.py`;
`tests/integration/test_rag_pipeline.py`. Also: dropped torch/transformers,
bumped tooling to Python 3.12.

### What
Built the local retrieval-augmented-generation pipeline: fetch arXiv abstracts →
sentence-aware chunking → embed → persist to ChromaDB → cosine search + BM25
re-rank → ranked `RetrievedPaper`s. Verified end-to-end on a live ingest (76
chunks) with retrieval working.

### Why
This is NeoWatch's "knowledge base." Agents (Phase 4) ask it for relevant papers
instead of relying on the LLM's training memory — grounding answers in real,
citable sources.

### Key decision: embeddings backend (ChromaDB ONNX, not sentence-transformers)
torch has no Intel-Mac (x86_64) wheel past 2.2.2, and 2.2.2 drags in an
incompatible numpy/transformers stack (we hit both errors live). Chose ChromaDB's
built-in **ONNX** build of the *same* model (`all-MiniLM-L6-v2`): identical
embeddings, ~5 fewer heavy deps, robust. `embed.py` is written as the **single
swap point** so moving to sentence-transformers later is a one-file change (plus a
re-index). See [[retrieval-concepts]] / `docs/RETRIEVAL_CONCEPTS.md`.

### Key concepts & tools introduced
- **Two-stage retrieval (the funnel)** — cheap dense cosine search for recall
  (top-20) → BM25 lexical re-rank for precision (top-5). The accuracy-vs-speed
  trade-off made concrete.
- **Embeddings as a versioned data contract** — vectors from different models
  aren't comparable; changing the model means re-indexing the whole store.
- **Chroma owns embedding** — the collection holds the embedding function, so
  documents (ingest) and queries (search) are guaranteed to use the same model.
- **cosine must be set explicitly** — `metadata={"hnsw:space": "cosine"}`; Chroma
  defaults to squared-L2.
- **Pure logic split from I/O again** — `bm25_scores()` is a pure function unit-
  tested with a 3-doc corpus, no Chroma/network. Same pattern as Phase 2's parsers.
- **Idempotent ingest** — a sidecar timestamp file + `is_stale()` make re-running
  ingest a cheap no-op unless `force=True` or >7 days old.

### Gotchas hit (and the lessons)
1. **numpy 2.x breaks torch 2.2.2** and **transformers 5.x needs torch ≥ 2.4** —
   two version walls that together make the sentence-transformers path unviable on
   this hardware. Confirmed the ONNX route sidesteps all of it.
2. **numpy's type stubs use 3.12 syntax** — had to bump mypy/ruff/`requires-python`
   from 3.11 to 3.12 (we're on 3.12 anyway). Tooling config must match the runtime.
3. **chromadb's `EmbeddingFunction` generic is contravariant** — our docs-only
   function is "too narrow" for mypy; one honest, commented `type: ignore` at the
   library boundary beats contorting our code.
4. **`zip(xs, xs[1:], strict=True)`** is wrong for pairwise iteration (lengths
   differ by one) — use `strict=False` intentionally.

### Honest result — a real retrieval-QUALITY finding (not a bug)
The live demo for `["Torino scale", "impact", "probability"]` ranked *"Scaling in
stock market data"* and a *baryon cosmology* paper **above** *"Global Asteroid Risk
Analysis"*. The on-topic papers were retrieved but out-ranked. Cause: pure-BM25
re-rank over short, generic keywords ("impact", "scale", "probability") rewards raw
lexical frequency regardless of domain, and our seed arXiv queries pulled a mixed
corpus. This is *exactly* the failure `RETRIEVAL_CONCEPTS.md` predicts. Fixes
(deferred until we have an eval harness to measure them): tighter seed queries
(category filters/quoted phrases), blend the dense similarity into the final score
instead of pure BM25, or add a cross-encoder re-ranker. Logged as the canonical
"you can't improve what you don't measure" lesson.

### Verification (all green)
`ruff` clean · `mypy --strict` clean (59 files) · 25/25 unit tests ·
5/5 live integration tests · live demo built a 76-chunk knowledge base and
retrieved from it.

---

## 2026-06-21 — Phase 2 (data layer) — COMPLETE

**Files:** `src/neowatch/data/{models,http,neows,horizons,apod,sbdb,arxiv,donki}.py`;
`tests/unit/test_models.py`; `tests/integration/test_data_clients.py`;
`tests/fixtures/{neows_feed.json,apod.json,sbdb.json,donki_flr.json,arxiv.xml}`.

### What
Built typed async clients for all six external sources (NASA NeoWs, JPL Horizons,
APOD, JPL SBDB, arXiv, NASA DONKI). Every response is validated into a Pydantic
model; every network call shares one retry policy and (for NASA) one rate-limit
counter. No LLM logic yet.

### Why
Agents (Phase 4) should consume *trustworthy typed objects*, never raw JSON. By
validating at the boundary, a changed/broken API fails loudly here instead of
surfacing as a weird bug three layers up inside an agent.

### Key concepts & tools introduced
- **fetch/parse split** — each client has an `async def fetch...()` (network) and
  a pure `def parse...()` (raw → model). The fragile part (parsing) is unit-tested
  against saved **fixtures** with zero network; only the thin fetch layer needs
  live tests. This is the phase's most important design choice.
- **Pydantic models as data contracts** — `_ApiModel` base sets
  `extra="ignore"` (an API *adding* a field won't break us) while a *missing
  required* field still errors. NASA sends numbers as strings → Pydantic coerces
  `str → float` automatically.
- **One shared retry policy (`tenacity`)** — `retry_external` = 3 attempts,
  exponential backoff (1s→2s→4s), only on transport/5xx errors, `reraise=True`
  so the original exception surfaces. Defined once, applied as a decorator.
- **Dependency injection over globals** — fetchers take `client`/`settings` as
  arguments instead of reaching for a global. Makes them trivially testable.
- **Thread-safe rate limiter** — NASA's key is shared across NeoWs/APOD/DONKI, so
  one process-wide counter (rolling hour, lock-guarded) prevents blowing the cap.
- **Test markers + opt-in live tests** — integration tests are marked and skipped
  unless `NEOWATCH_RUN_INTEGRATION=1`, so the default gate is fast and offline.

### Gotchas hit (and the lessons) — all caught by the live integration tests
1. **arXiv `http://` → 301 redirect**, and httpx does **not** follow redirects by
   default. Fix: `follow_redirects=True` on the shared client + use `https://`.
   Lesson: integration tests earn their keep — unit tests alone would've missed this.
2. **SBDB 400 Bad Request** — the spec's `close-app=true` is not a real SBDB
   parameter, and SBDB rejects unknown params. Dropped it (our model doesn't use
   close-approach data anyway). Lesson: trust the live API over the spec draft.
3. **mypy `max()` over `Any | None`** — filtering `None` in a comprehension doesn't
   narrow the type for mypy; an explicit typed loop does.
4. **feedparser has no type stubs** — added a scoped `[[tool.mypy.overrides]]`
   `ignore_missing_imports` so strict mode stays strict everywhere else.

### Verification (all green)
`ruff` clean · `mypy --strict` clean (56 files) · 17/17 unit tests ·
4/4 live integration tests (NeoWs, APOD, SBDB, arXiv).

### Known follow-up
- Horizons returns a free-form text block; we keep it raw in `EphemerisData`
  rather than over-fitting a parser. Extract specific quantities if a later phase
  needs them.
- The Phase 3 embeddings decision is now unblocked by the 3.12 switch (torch +
  sentence-transformers can install); still to be done when Phase 3 starts.

---

## 2026-06-21 — Switched interpreter to Python 3.12

### What
Rebuilt the project virtualenv on **Python 3.12.4** (was 3.13). No source code
changed — every Phase-1 file is pure, version-agnostic Python — so this was a
fresh `python3.12 -m venv .venv` + reinstall, not a migration.

### Why
The Intel-Mac (x86_64) RAG blocker. PyTorch's **last** macOS x86_64 wheels ship
for torch 2.2.2, which supports CPython **3.8–3.12 only** — there is no x86_64
wheel for 3.13 at any torch version. Dropping to 3.12 is the one move that lets
`torch` + `sentence-transformers` install on this machine, so the spec's
embedding stack works unchanged in Phase 3.

### Trade-offs
- **3.12 vs. ChromaDB ONNX embeddings (the other option):** staying on 3.13 +
  ChromaDB's built-in ONNX model would have avoided torch entirely, but it
  diverges from the spec and gives less control over the embedding model. 3.12
  keeps us on the prescribed stack at the cost of a slightly older interpreter.
- Python 3.12 is mature and fully supported; losing 3.13 costs us nothing this
  project uses.

### Gotchas / notes
- The old 3.13 venv **and `.env`** were gone at session start — both are
  git-ignored, ephemeral files that don't persist across sessions. Source files
  survived. Recreated `.env` from `.env.example`; **keys must be re-pasted into
  the file** (never into chat).
- `python@3.12` was already present via Homebrew, so no manual download needed.
- Newer `ruff` (0.15) flagged a stray blank line the old version ignored — a
  reminder that unpinned dev-tool versions can shift lint rules between installs.

### Verification (all green, re-run on 3.12)
`ruff` clean · `mypy --strict` clean (54 files) · 11/11 tests pass ·
`import neowatch` OK. **Live API-key checks pending** — they need the repopulated
`.env`.

---

## 2026-06-20 — Phase 1 (project foundation) — COMPLETE

**Files:** `pyproject.toml`, `src/neowatch/config.py`, `logging_config.py`,
`context.py`, `agents/base.py`, `main.py`; `tests/unit/test_config.py`,
`test_context.py`, `test_logging.py`.

### What
Turned the stubs into a runnable, type-checked skeleton: a `Settings` config
object, structured JSON logging with secret redaction, the shared `AgentContext`
/ `AgentResult` models, and the abstract `BaseAgent` contract. Got the whole
thing green (ruff + mypy strict + pytest) and confirmed both API keys work.

### Why
Everything later stands on these four primitives. Building + verifying them in
isolation (no agents yet) means later bugs are *logic* bugs, not foundation bugs.

### Key concepts & tools introduced
- **`pydantic-settings` + `SecretStr`** — config loaded from env/`.env`; secrets
  are masked in logs/reprs and only unwrapped at point of use.
- **`lru_cache` on `get_settings()`** — build config once per process; a cheap
  "singleton" without a global variable.
- **`structlog`** — logs are JSON dicts, not text. A custom `strip_secrets`
  processor redacts key/email patterns as defence-in-depth.
- **`ABC` / `@abstractmethod`** — `BaseAgent` is a contract subclasses must
  fulfil; the orchestrator can treat every agent uniformly.
- **mypy `--strict` + `pydantic.mypy` plugin** — the plugin teaches mypy that
  `BaseSettings()` is populated from the environment (so no-arg construction is
  valid). Lesson: an *unused* `# type: ignore` is itself an error under strict.
- **`src/` layout + editable install (`pip install -e .`)** — tests import the
  installed package, exactly as a user would.

### Gotchas hit (and the lessons)
1. **`cmd && echo DONE || echo FAIL` lies about success** — it reports the
   echo's exit code, not the command's. The background pip install *failed* but
   looked like it passed. Lesson: check the real exit code / the actual log.
2. **Intel Mac + Python 3.13 can't install `torch`** — no wheel exists for that
   combo, which blocks `sentence-transformers`. Phase 1 needs neither, so we
   installed only Phase-1 deps and deferred the ML-stack decision to Phase 3.
3. **Empty env value != unset** — `SERP_API_KEY=` in `.env` becomes
   `SecretStr('')`, not `None`. Unit tests must isolate from the real `.env`
   (`_env_file=None`) to assert code defaults deterministically.

### Verification (all green)
`ruff` clean · `mypy --strict` clean (48 files) · 11/11 unit tests pass ·
`python -m neowatch.main` emits a structured startup log · both API keys
validated with zero-cost live calls.

### Known follow-up
- **Phase 3 blocker:** decide how to handle embeddings on Intel Mac + 3.13
  (switch to Python 3.12 for the full `torch`/`sentence-transformers` stack, or
  drop `sentence-transformers` and use ChromaDB's built-in ONNX embeddings).
- `requirements.txt` still lists the full stack; it installs cleanly only once
  the Phase 3 decision is made.

---

## 2026-06-20 — Phase 0 scaffolding (project skeleton)

**Files:** entire `src/neowatch/**` stub tree, `tests/**`, `requirements.txt`,
`.env.example`, `.gitignore`, `docs/PLAN.md` (learning rule + Phase 0 added).

### What
Created the full directory structure as **docstring-only stubs** (no logic yet),
plus the dependency list, the secrets template, and git-ignore rules.

### Why
Establishing the skeleton first gives every later phase a known home for its
code and lets us reason about the architecture as a whole before writing any
logic. Each stub's docstring states *why the module exists*, so the structure
itself documents the design.

### Trade-offs
- **Stub-first vs. build-as-you-go:** stubbing everything up front risks creating
  files we later rename, but it makes the architecture legible immediately and
  matches the spec's prescribed layout. Worth it for a learning project.
- **One big explanation vs. per-file:** these stubs are trivial, so explaining
  each one individually would burn tokens without teaching anything. The real
  per-step teaching happens when we write implementation code.

### Tools / concepts introduced
- **`src/` layout** — package lives under `src/` so tests import the *installed*
  package, not loose files (avoids "works on my machine" import bugs).
- **`requirements.txt`** — the dependency manifest; `pip install -r` reproduces
  the environment.
- **`.env` / `.env.example`** — real secrets in git-ignored `.env`; a committed
  template (`.env.example`) shows what's needed without leaking keys.
- **`.gitignore`** — keeps secrets, caches, the venv, and the vector store out of
  version control.

### What to notice
The structure maps 1:1 to the spec's architecture: `data/` (API clients) feeds
`rag/` + `calc/`, the `agents/` use those, `guardrails/` wrap them, and `ui/`
sits on top via `pipeline.py`. Dependencies flow one direction: low-level → agents
→ pipeline → UI.

---
