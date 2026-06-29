# NeoWatch — Improvement Backlog

Findings from the 2026-06-27 architecture review. Priority order. Tier 1 is the
recommended next work. Each item lists the exact target, the approach, and what
"done" looks like. The reasoning/lessons are in
[`LEARNING_LOG.md`](LEARNING_LOG.md) (2026-06-27 entry).

Workflow reminder: learning-mode project — narrate What/Why/Trade-offs inline and
in the LEARNING_LOG, keep teaching docstrings, run ruff + mypy + the offline test
suite before committing, and never stage `.env` or cache dirs.

---

## Tier 1 — do these next (high value, low risk)

### 1. Structured outputs for synthesis (replace the brittle JSON regex)
**Why:** `SynthesisAgent` asks Sonnet for prose-as-JSON and scrapes it with a greedy
`\{.*\}` regex. Any braces in surrounding prose → parse silently returns `{}` →
**empty report, no error.** This is the highest-risk fragility in the codebase.

**Targets:**
- `src/neowatch/agents/synthesis_agent.py`
  - `_JSON_RE` (line ~42) and `_parse_prose` (line ~231) — to be removed.
  - `_write_prose` (lines ~89–105) — the `messages.create` call to convert.

**Approach:**
- Define a Pydantic model for the prose shape the code already expects:
  `executive_summary: str`, `literature_insights: str`,
  `event_summaries: list[EventSummary]` where `EventSummary` is
  `{object_id: str, summary: str}`.
- Switch `_write_prose` from `client.messages.create(...)` + regex to
  `client.messages.parse(model=sonnet_model, max_tokens=4096, temperature=0.4,
  system=SYNTHESIS_V1, messages=[...], output_format=ProseModel)` and read
  `resp.parsed_output` (a validated model instance). `temperature` is still valid on
  Sonnet 4.6. Keep the token accounting (`context.add_tokens(...)`).
- Delete `_JSON_RE` / `_parse_prose`. Update `_build_events` to take the typed
  `event_summaries` instead of `list[Any]` dicts.
- The `SYNTHESIS_V1` prompt can drop its "respond with JSON" framing (the schema now
  enforces it) but keep the grounding/never-invent-numbers instructions.

**Done when:** synthesis returns a populated report from a typed object (no regex);
a new unit test feeds a model response that previously broke the regex and asserts a
well-formed report; ruff + mypy + 77+ tests green.

### 2. Prompt caching on the FetchAgent loop
**Why:** `FetchAgent`'s Haiku loop carries raw NASA tool results in its message
history and re-sends them each of up to 6 iterations (~4.8k tokens — the source of
the earlier budget bug). That's *above* Haiku 4.5's 4096-token cache minimum, so
caching the prefix makes later iterations re-read prior turns at ~0.1×.

**Targets:**
- `src/neowatch/agents/fetch_agent.py` — the `messages.create` call (line ~71).

**Approach:**
- Add `cache_control={"type": "ephemeral"}` (top-level auto-caching — caches the last
  cacheable block) to the `messages.create` call.
- Verify it actually caches: log/inspect `resp.usage.cache_read_input_tokens` on a
  live run; it should be > 0 on iterations after the first. If it's always 0, the
  prefix is under the minimum or an invalidator is present.
- **Do NOT** bother caching the orchestrator loop — its per-iteration prompt (status
  strings only) is below the cache minimum, so it's a near-no-op there.

**Done when:** a live fetch run shows non-zero `cache_read_input_tokens` on later
iterations; offline tests still green (FakeAnthropic ignores the param).

---

## Tier 2 — correctness / clarity (do while the budget logic is fresh)

### 3. Disentangle the token budget's two meanings
**Why:** `context.tokens_used` accumulates cumulative billed cost, but
`TokenBudgetGuardrail._compress` (token_budget.py line ~128) re-baselines it to a
char-estimate of current history — silently changing what the 200k ceiling means
after the first compression.

**Targets:** `src/neowatch/context.py` (`add_tokens`, `tokens_used`),
`src/neowatch/guardrails/token_budget.py` (`_compress`, `_estimate_tokens`, `ratio`).

**Approach:** track two fields — a monotonic `cost_tokens` (only grows; drives the
session-cost budget) and a separate `context_tokens` estimate (drives the
compress/keep-last decision). Compression reduces the latter, never the former.
Consider replacing the char-estimate with summed `resp.usage` where available.

### 4. One shared Anthropic client per run, closed at the end
**Why:** in production each agent builds its own `AsyncAnthropic` via
`get_anthropic_client`, and none are closed — leaking connection pools per request.

**Targets:** `src/neowatch/pipeline.py` (`run_query`, lines ~48–57),
`src/neowatch/llm.py`.

**Approach:** build one client in `run_query`, thread it through orchestrator +
synthesis (they already accept `client`), and close it (`async with` or
`await client.aclose()`).

---

## Tier 3 — robustness / UX (later)

### 5. Log non-`tool_use` stop reasons in the loops
Both loops do `if resp.stop_reason != "tool_use": break`. If Haiku hits `max_tokens`
(1024) or `refusal`, they proceed with partial data silently. Log `stop_reason` when
it's `max_tokens`/`refusal` in `fetch_agent.py` and `orchestrator.py`.

### 6. Topic-relevant imagery
APOD is fetched by date range, so "show me an image" returns *that day's* picture, not
a topic match (the live-run caveat). Optionally swap to NASA's image-search API keyed
on query terms when the query implies imagery. Larger scope.

### 7. Synthesis parse-failure regression test
Cheap guard even after #1 lands.
