# NeoWatch — Phased Implementation Plan

**Status:** Pre-implementation
**Source of truth:** [`docs/PROJECT_SPEC.md`](./PROJECT_SPEC.md)
**Audience:** Any engineer (human or agent) executing a phase independently.

---

## How to use this document

Each phase below contains four sections:

1. **Objective** — what "done" means for the phase, in one paragraph.
2. **Files to create** — exact absolute-from-root paths, grouped by concern.
3. **Step-by-step tasks** — ordered, executable steps with enough detail to
   implement without re-reading the whole spec.
4. **Verification checklist** — concrete checks (commands + observable outcomes)
   that must all pass before starting the next phase.

**Global rules (apply to every phase):**

- Python 3.11+, async-first (`httpx.AsyncClient`, `asyncio.gather`).
- Every data structure is a Pydantic v2 model — never pass bare dicts between agents.
- Type hints on every function (return types included); `mypy src/` must pass clean.
- Google-style docstrings on every class and public method.
- Structured logging via `structlog` only — no `print()`, no bare `logging`.
- All external calls wrapped in `tenacity` retry with exponential backoff.
- Secrets only via `.env` + `pydantic-settings`. Never hardcode.
- Model routing: `claude-haiku-4-5` for tool calls / cheap reasoning,
  `claude-sonnet-4-6` for orchestration planning and final synthesis.
- Each phase ends green: `ruff check`, `mypy`, and `pytest` all pass before moving on.

---

## Learning mode (this project is a learning exercise — read first)

**The primary goal of this project is for the developer to learn**, not just to
ship working code. Every "step" in this plan must therefore be *taught*, not just
*executed*. Whenever code is written or a decision is made, it is accompanied by
a **brief, plain-English explanation** covering four things:

1. **What** — what we're building or changing, in one or two sentences.
2. **Why** — why it's needed and why it's done this way.
3. **Trade-offs** — what alternatives exist and what we gave up by choosing this.
4. **Tools** — which library/service/API/pattern is used, and what it does for us.

Keep explanations short and concrete (a few sentences each, jargon defined on
first use). The aim is understanding, not exhaustive documentation.

### How this is delivered in Claude Code (chosen method)

Cursor surfaces this kind of running commentary in its sidebar. Claude Code's
equivalent is the **chat/terminal output the assistant prints around its tool
calls** (rendered as markdown). So the method is:

- **Inline narration (primary):** before each meaningful chunk of work, the
  assistant posts a short *What / Why / Trade-offs / Tools* note in the chat,
  then writes the code, then adds a one-line "what to notice" recap. This is the
  closest equivalent to the Cursor sidebar and requires no extra files.
- **Persistent learning log (durable backup):** because chat scrolls away, the
  same explanations are appended to **`docs/LEARNING_LOG.md`**, one short entry
  per step/phase. This gives a reviewable record to revisit later. Each entry is
  dated and tagged with the phase and file(s) it covers.
- **Teaching docstrings:** module and class docstrings briefly state the *why*
  and the key concept, not just the *what*, so the code itself reinforces the
  lesson.

> When executing any phase, treat "explain as you go (What / Why / Trade-offs /
> Tools), narrate in chat, and append to `docs/LEARNING_LOG.md`" as a mandatory
> global rule — equal in weight to the lint/type/test gates.

This learning directive applies to **Phase 0 onwards**.

---

## Phase 0 — Prerequisites, accounts & local environment

### Objective
Before any code runs, get every external account, API key, and local tool in
place, and understand what each one is *for*. This phase is a guided walkthrough:
the developer performs the sign-ups (the assistant cannot create accounts or
accept terms on their behalf), and the assistant explains each service, its
cost/limits, and how its key flows into the app via `.env`.

### What needs an account or key (and what doesn't)

| Service | Needed? | Cost | Used by | Sign-up |
|---|---|---|---|---|
| **Anthropic API** (`ANTHROPIC_API_KEY`) | **Required** | **Paid** — pay-as-you-go credits, no real free tier | Every agent (Haiku + Sonnet) | console.anthropic.com → add billing → create API key |
| **NASA API** (`NASA_API_KEY`) | **Required** | Free (1,000 req/hr) | FetchAgent (NeoWs), APOD, DONKI | api.nasa.gov → fill form → key emailed instantly |
| **JPL Horizons** | No key | Free | FetchAgent ephemeris | none — open API |
| **JPL SBDB** | No key | Free | FetchAgent physical params | none — open API |
| **arXiv API** | No key | Free | RAG ingestion | none — open API |
| **SERP API** (`SERP_API_KEY`) | Optional/unused | Free tier exists | not used (arXiv needs no key) | skip for now |
| **HuggingFace** | Deferred to Phase 8 | Free CPU tier | Deployment only | huggingface.co → account (do later) |

### Local prerequisites
- **Python 3.11+** — confirm with `python --version` (must be ≥ 3.11).
- **A terminal + this repo** — already present.
- **(Phase 8 only)** Docker Desktop and a HuggingFace account — can be deferred.

### Step-by-step tasks (developer-driven, assistant-guided)
1. **Verify Python.** Run `python --version` (or `python3 --version`). If below
   3.11, install 3.11+ first. *(Why: the codebase uses 3.11+ syntax and typing.)*
2. **Create the Anthropic API key.** Go to console.anthropic.com, sign up, add a
   payment method, purchase a small amount of credit, then create an API key
   (starts with `sk-ant-`). *(Why: this is the brain of every agent. Trade-off:
   it costs money per token — the project's token-budget guardrails exist
   partly to keep this spend small and predictable.)*
3. **Create the NASA API key.** Go to api.nasa.gov, fill the "Generate API Key"
   form; the key arrives by email immediately. *(Why: powers asteroid feed, APOD
   images, and DONKI space weather. Free, but rate-limited to 1,000/hr — hence
   the rate limiter in Phase 2.)*
4. **Note the keyless APIs.** Horizons, SBDB, and arXiv need no sign-up. *(Why:
   good to know which calls can fail on *their* downtime vs. our auth.)*
5. **Skip SERP and HuggingFace for now.** SERP is unused; HuggingFace is only for
   Phase 8 deployment. *(Trade-off: defer setup until it's actually needed.)*
6. **Create the local `.env`.** Copy `.env.example` to `.env` and paste in the
   two real keys. *(Why: `.env` is git-ignored so secrets never get committed;
   `pydantic-settings` loads them at runtime. Never hardcode keys in code.)*
7. **Sanity-check the keys** (after Phase 1/2 exist) with a single tiny request
   each, so a bad key is caught early rather than mid-pipeline.

### Verification checklist
- [ ] `python --version` reports 3.11 or higher.
- [ ] `ANTHROPIC_API_KEY` exists, starts with `sk-ant-`, and has billing/credit attached.
- [ ] `NASA_API_KEY` received and saved.
- [ ] `.env` created from `.env.example`, contains both keys, and is git-ignored.
- [ ] Developer can explain, in one sentence each, what the Anthropic and NASA keys are for.
- [ ] No key value is pasted into any tracked file (only into `.env`).

---

## Phase 1 — Project foundation

### Objective
Establish a runnable, type-checked, lint-clean Python package skeleton with a
working configuration system (env-driven), structured logging, a shared
`AgentContext` object, and an abstract `BaseAgent` contract that every later
agent will inherit. No external API calls yet — this phase proves the scaffold
imports, configures, and logs correctly.

### Files to create
- `pyproject.toml` — build config, tool config (ruff, mypy, pytest).
- `src/neowatch/__init__.py` — package version + public exports.
- `src/neowatch/config.py` — `Settings` via `pydantic-settings`.
- `src/neowatch/logging_config.py` — `structlog` setup + secret-stripping processor.
- `src/neowatch/context.py` — `AgentContext` + `AgentResult` Pydantic models.
- `src/neowatch/agents/__init__.py`
- `src/neowatch/agents/base.py` — abstract `BaseAgent`.
- `src/neowatch/main.py` — app entry point (stub that builds config + logging).
- `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`
- `tests/unit/test_config.py`, `tests/unit/test_context.py`
- `.gitignore`

### Step-by-step tasks
1. **`pyproject.toml`**: declare `[project]` (name `neowatch`, Python `>=3.11`),
   set `[tool.setuptools.packages.find]` to `src`, configure `[tool.ruff]`
   (line length 100, target py311), `[tool.mypy]` (`strict = true`,
   `python_version = 3.11`), and `[tool.pytest.ini_options]` with
   `asyncio_mode = "auto"` and `testpaths = ["tests"]`.
2. **`config.py`**: define `Settings(BaseSettings)` with fields:
   `anthropic_api_key: SecretStr`, `nasa_api_key: SecretStr`,
   `serp_api_key: SecretStr | None = None`,
   `haiku_model: str = "claude-haiku-4-5"`,
   `sonnet_model: str = "claude-sonnet-4-6"`,
   `token_budget_per_session: int = 200_000`,
   `max_tokens_per_agent: int = 4096`,
   `chroma_persist_dir: str = ".chroma"`,
   `log_level: str = "INFO"`. Configure
   `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`.
   Expose a cached `get_settings()` via `functools.lru_cache`.
3. **`logging_config.py`**: `configure_logging(level: str)` wiring `structlog`
   with `TimeStamper`, `add_log_level`, JSON renderer, and a custom processor
   `strip_secrets` that redacts API-key-like and email-like substrings.
4. **`context.py`**: `AgentContext` (holds `query: str`, `history: list`,
   `tokens_used: int`, `nasa_call_count: int`, plus a session cache dict) and
   `AgentResult` (holds `agent_name: str`, `success: bool`, `data`, `error`).
   Add `compress_history()` and `add_tokens()` method stubs (signatures only —
   real compression lands in Phase 5).
5. **`agents/base.py`**: abstract `BaseAgent` with `__init__(self, settings, logger)`
   and abstract `async def run(self, context: AgentContext) -> AgentResult`.
6. **`main.py`**: `def main()` that calls `get_settings()`, `configure_logging`,
   logs a startup line, and (for now) prints nothing — UI lands in Phase 7.
   Guard with `if __name__ == "__main__": main()`.
7. **Tests**: `test_config.py` monkeypatches env vars and asserts `Settings`
   loads them; `test_context.py` asserts `AgentContext` defaults and that
   `add_tokens` increments `tokens_used`.

### Verification checklist
- [~] `pip install -r requirements.txt` — Phase-1/2 deps installed; the full
  file's ML stack (`torch`/`sentence-transformers`) is deferred to Phase 3. Venv
  rebuilt on **Python 3.12** (x86_64), which restores `torch` wheel availability.
- [x] `python -c "import neowatch; from neowatch.config import get_settings"` works.
- [x] `python -m neowatch.main` runs without error and emits a structured startup log.
- [x] `ruff check src/ tests/` → no errors.
- [x] `mypy src/` → no errors.
- [x] `pytest tests/unit -v` → all pass (11/11).
- [x] No secret value appears in any emitted log line (verified via `strip_secrets` tests).
- [x] Bonus: both API keys validated with zero-cost live calls.

---

## Phase 2 — Data layer

### Objective
Implement strongly-typed async clients for every external data source (NASA
NeoWs, JPL Horizons, APOD, JPL SBDB, arXiv, NASA DONKI). Every response is
parsed into a Pydantic model; every call retries with backoff; NASA calls share
a session rate-limit counter. No LLM logic in this phase.

### Files to create
- `src/neowatch/data/__init__.py`
- `src/neowatch/data/models.py` — all source-data Pydantic models.
- `src/neowatch/data/http.py` — shared async client factory + retry decorator + rate limiter.
- `src/neowatch/data/neows.py` — NeoWs client (`feed`, `neo detail`, `browse`).
- `src/neowatch/data/horizons.py` — JPL Horizons ephemeris client.
- `src/neowatch/data/apod.py` — APOD image-metadata client.
- `src/neowatch/data/sbdb.py` — JPL Small Body Database client.
- `src/neowatch/data/arxiv.py` — arXiv Atom-feed client (`feedparser`).
- `src/neowatch/data/donki.py` — DONKI space-weather client (`FLR`, `CME`, `GST`).
- `tests/unit/test_models.py`
- `tests/integration/test_data_clients.py`
- `tests/fixtures/` — saved JSON/XML sample responses for offline tests.

### Step-by-step tasks
1. **`models.py`**: define (at minimum) `NEOFeedItem`, `NEODetail`,
   `CloseApproach`, `EstimatedDiameter`, `EphemerisData`, `APODImage`,
   `SBDBRecord`, `ArxivPaper`, `SpaceWeatherEvent`, `SpaceWeatherReport`.
   Use strict types (`float`, `datetime`, `HttpUrl`) and field aliases that
   match the raw API JSON keys (e.g. `miss_distance`, `relative_velocity`).
2. **`http.py`**: `get_async_client()` returns a configured `httpx.AsyncClient`
   (timeout 30s, sane headers). Define a reusable `retry_external` =
   `tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(1,4))`.
   Implement `NasaRateLimiter` tracking calls/hour, raising/backing off at 900.
3. **`neows.py`**: `async def get_neo_feed(start_date, end_date)`,
   `get_neo_detail(neo_id)`, `browse(page)`. Build URLs against
   `https://api.nasa.gov/neo/rest/v1/`, append `api_key` from settings,
   parse into `NEOFeedItem`/`NEODetail`. Increment the rate limiter per call.
4. **`horizons.py`**: `async def get_ephemeris(target, date)` querying
   `https://ssd.jpl.nasa.gov/api/horizons.api`; parse the text/JSON block into
   `EphemerisData`. No API key.
5. **`apod.py`**: `async def get_apod(date)` and `get_apod_range(start, end)`
   against `https://api.nasa.gov/planetary/apod`; parse into `APODImage`.
6. **`sbdb.py`**: `async def get_sbdb(sstr)` with `phys-par=true&close-app=true`;
   parse into `SBDBRecord`. No API key.
7. **`arxiv.py`**: `async def search_arxiv(query, max_results=20)`; fetch the
   Atom feed, parse with `feedparser`, map entries to `ArxivPaper`.
8. **`donki.py`**: `async def get_flares/get_cmes/get_storms(start, end)` and a
   `get_space_weather()` aggregator returning `SpaceWeatherReport`.
9. **Caching**: each client checks `context.session_cache` (or an injected cache)
   before issuing duplicate calls. (Cache wiring may be light here and finalised
   in Phase 4.)
10. **Tests**: unit tests validate model parsing against saved fixtures;
    integration tests (marked `@pytest.mark.integration`, skipped without keys)
    hit the live APIs once each.

### Verification checklist
- [x] Every client function returns a Pydantic model (or list of them), never a raw dict.
- [x] `pytest tests/unit/test_models.py -v` parses all fixtures cleanly.
- [x] Integration tests succeed against live APIs when keys are present.
- [x] A forced HTTP error triggers exactly 3 retry attempts with backoff (assert via mock).
- [x] NASA rate limiter increments and warns near 900 calls (unit-tested with a stub).
- [x] `mypy src/neowatch/data` and `ruff check src/neowatch/data` pass clean.

---

## Phase 3 — RAG pipeline

### Objective
Build the local retrieval-augmented-generation pipeline: ingest arXiv abstracts,
chunk them, embed with `all-MiniLM-L6-v2`, persist to ChromaDB, and retrieve
with cosine search + BM25 re-rank. Output is a ranked list of `RetrievedPaper`
objects ready for synthesis.

### Files to create
- `src/neowatch/rag/__init__.py`
- `src/neowatch/rag/models.py` — `Chunk`, `RetrievedPaper`.
- `src/neowatch/rag/chunk.py` — sentence-split + 512-token windowing (50 overlap).
- `src/neowatch/rag/embed.py` — `sentence-transformers` wrapper (lazy-loaded model).
- `src/neowatch/rag/store.py` — ChromaDB collection management (`neowatch_papers`).
- `src/neowatch/rag/ingest.py` — `ingest_arxiv_papers()` orchestration.
- `src/neowatch/rag/retrieve.py` — cosine query + BM25 re-rank.
- `tests/unit/test_chunk.py`, `tests/unit/test_retrieve.py`
- `tests/integration/test_rag_pipeline.py`

### Step-by-step tasks
1. **`models.py`**: `Chunk(text, paper_id, chunk_index, metadata)` and
   `RetrievedPaper(title, authors, abstract, arxiv_id, published, url, relevance_score)`.
2. **`chunk.py`**: `chunk_text(text)` using `nltk.sent_tokenize`, grouping
   sentences into ~512-token windows with 50-token overlap. Download the `punkt`
   tokenizer on first use (guarded). Return `list[Chunk]`.
3. **`embed.py`**: lazily load `sentence-transformers/all-MiniLM-L6-v2`;
   `embed_texts(texts) -> list[list[float]]`. Cache the model as a module global.
4. **`store.py`**: `get_collection()` returning a persistent ChromaDB collection
   at `settings.chroma_persist_dir`. Helpers: `upsert_chunks`, `count`,
   `is_stale(max_age_days=7)` (track an ingest timestamp in collection metadata).
5. **`ingest.py`**: `async def ingest_arxiv_papers()` that runs the four spec
   queries (each 20 results), chunks abstracts, embeds, and upserts. Idempotent:
   skips if collection fresh unless `force=True`.
6. **`retrieve.py`**: `retrieve(keywords, top_k=5)` — embed keywords, cosine
   search top-20 in ChromaDB, then BM25 re-rank (`rank_bm25`) down to top-5,
   returning `list[RetrievedPaper]`. Deduplicate by `arxiv_id`.
7. **Tests**: `test_chunk.py` asserts overlap and token bounds; `test_retrieve.py`
   asserts BM25 re-rank order on a tiny fixture corpus; integration test runs a
   real ingest of a small query and retrieves a relevant paper.

### Verification checklist
- [x] First-run downloads the embedding model + `punkt` and caches them locally.
- [x] `ingest_arxiv_papers()` populates `neowatch_papers` (assert `count() > 0`). (76 chunks)
- [x] Re-running ingest on a fresh collection is a no-op (idempotency check).
- [x] `retrieve(["Torino scale"])` returns ≤5 `RetrievedPaper`, sorted by score.
- [x] `is_stale()` returns True after simulating a >7-day-old timestamp.
- [x] `mypy src/neowatch/rag` and `ruff check src/neowatch/rag` pass clean.

> **Embeddings decision (resolved):** ChromaDB built-in **ONNX** `all-MiniLM-L6-v2`
> instead of `sentence-transformers`/`torch` (no Intel-Mac x86_64 torch wheel past
> 2.2.2). Same model, far fewer deps. `embed.py` is the single swap point.
> **Known quality gap:** the pure-BM25 re-rank over short generic keywords promotes
> some lexically-keyword-heavy but off-topic papers above on-topic ones — exactly
> the failure mode in `RETRIEVAL_CONCEPTS.md`. Improvable via better seed queries,
> dense+BM25 score blending, or a cross-encoder; deferred until we have an eval
> harness to measure the change.

---

## Phase 4 — Agent system

### Objective
Implement the four specialist agents (Fetch, RAG, Calc, Image) as `BaseAgent`
subclasses, each exposing its capabilities as Claude tool definitions where
applicable, returning typed `AgentResult` payloads. CalcAgent performs all maths
in pure numpy/scipy; the LLM only narrates.

### Files to create
- `src/neowatch/tools/__init__.py`
- `src/neowatch/tools/schemas.py` — Claude tool-use JSON schemas for each tool.
- `src/neowatch/tools/fetch_tools.py` — callables: `get_neo_feed`, `get_neo_detail`,
  `get_space_weather`, `get_ephemeris`.
- `src/neowatch/agents/fetch_agent.py` — `FetchAgent`.
- `src/neowatch/agents/rag_agent.py` — `RAGAgent`.
- `src/neowatch/agents/calc_agent.py` — `CalcAgent`.
- `src/neowatch/agents/image_agent.py` — `ImageAgent`.
- `src/neowatch/calc/__init__.py`
- `src/neowatch/calc/orbital.py` — deterministic orbital/risk maths.
- `src/neowatch/calc/models.py` — `OrbitalAnalysis`, `RiskAssessment`.
- `src/neowatch/agents/models.py` — `NEOData`, `ImageAsset` (+ shared agent I/O).
- `tests/unit/test_calc_orbital.py`, `tests/unit/test_fetch_agent.py`,
  `tests/unit/test_image_agent.py`

### Step-by-step tasks
1. **`tools/schemas.py`**: define Anthropic tool-use schemas (name, description,
   `input_schema`) for the four FetchAgent tools, matching the spec signatures.
2. **`tools/fetch_tools.py`**: thin async wrappers around Phase 2 data clients,
   returning Pydantic models; these are the functions the tool dispatcher invokes.
3. **`fetch_agent.py`**: `FetchAgent.run()` drives a Haiku tool-use loop —
   sends the tool schemas, dispatches `tool_use` blocks to `fetch_tools`, feeds
   results back, and assembles a `NEOData` object. Implements the spec chunking
   rule: sort feed by `miss_distance` ASC, keep top 10, summarise the remainder
   as a statistical count. Caches calls in `context.session_cache`.
4. **`calc/orbital.py`**: pure functions — `km_to_lunar_distance`, `km_to_au`,
   `classify_velocity`, `cross_check_torino`, `detect_anomaly`,
   `observation_window`. No LLM, fully deterministic, all typed.
5. **`calc/models.py`**: `OrbitalAnalysis` (per-object computed fields) and
   `RiskAssessment` (object id, torino, computed risk band, rationale).
6. **`calc_agent.py`**: `CalcAgent.run()` calls `calc/orbital.py` to produce
   `OrbitalAnalysis`, then uses Haiku **only** to add narrative framing — never
   to alter a number. Numerical outputs are returned verbatim for FactCheck.
7. **`image_agent.py`**: `ImageAgent.run()` queries APOD over the date range,
   validates each image URL is reachable, resizes with `pillow` (max 800px),
   and returns `list[ImageAsset]` each carrying a credit/attribution string.
8. **`rag_agent.py`**: `RAGAgent.run()` takes keywords from context, calls
   Phase 3 `retrieve()` (triggering ingest if stale), returns `list[RetrievedPaper]`.
9. **Tests**: deterministic calc tests with known inputs/outputs; fetch/image
   agent tests use mocked data clients (no live calls).

### Verification checklist
- [x] Each agent subclasses `BaseAgent` and implements `async run() -> AgentResult`.
- [x] FetchAgent caps enumerated NEOs at 10 and reports a remainder count. (`_assemble` test)
- [x] All calc functions are pure (same input → same output; no I/O), unit-tested.
- [x] CalcAgent's returned numbers equal `calc/orbital.py` output exactly. (asserted field-for-field)
- [x] ImageAgent rejects unreachable URLs and attaches attribution to every asset.
- [x] RAGAgent returns typed `RetrievedPaper` objects. (thin adapter: offline-stubbed
  unit test here + live retrieval already proven by the Phase 3 integration test;
  exercised end-to-end in Phase 6.)
- [x] `mypy src/neowatch/agents src/neowatch/calc src/neowatch/tools` passes clean
  (whole-package `mypy src/` clean, 49 files).

> **LLM client + cost note:** specialist agents run on **Haiku 4.5** (cheap, fast;
> no `thinking`/`effort` params — Haiku rejects them). Agents take an injectable
> Anthropic client so every unit test uses a `FakeAnthropic` (`tests/unit/fakes.py`)
> — **zero paid API calls in the suite.** NASA/APOD I/O is mocked with httpx
> `MockTransport`. The hand-built tool/message payload dicts are `cast` to the SDK
> TypedDicts at the `messages.create` boundary (the SDK's types are stricter than
> our JSON-schema dicts). The `is_potentially_hazardous_asteroid` field name was
> caught by mypy before runtime — a concrete win for `--strict`.

---

## Phase 5 — Guardrails and safety

### Objective
Implement the three guardrail layers: input `DomainGuardrail` (domain + injection
+ length + harm checks), output `FactCheckLayer` (numeric claim verification
against a grounding context), and `TokenBudgetGuardrail` (budget warnings +
history compression). Wire secret-stripping into logs and finalise input
sanitisation.

### Files to create
- `src/neowatch/guardrails/__init__.py`
- `src/neowatch/guardrails/models.py` — `GuardrailResult`, `FactCheckReport`, `FlaggedClaim`.
- `src/neowatch/guardrails/domain.py` — `DomainGuardrail`.
- `src/neowatch/guardrails/factcheck.py` — `FactCheckLayer` + `GroundingContext` builder.
- `src/neowatch/guardrails/token_budget.py` — `TokenBudgetGuardrail` + compression.
- `src/neowatch/guardrails/sanitise.py` — prompt-injection pattern detection.
- `tests/unit/test_domain_guardrail.py`, `tests/unit/test_factcheck.py`,
  `tests/unit/test_token_budget.py`

### Step-by-step tasks
1. **`models.py`**: `GuardrailResult(allowed: bool, reason: str)`,
   `FlaggedClaim(value, source_value, pct_diff, location)`,
   `FactCheckReport(flagged: list[FlaggedClaim], confidence: str)`.
2. **`sanitise.py`**: regex patterns for `ignore previous`, `system:`, `<|`,
   `HUMAN:`, etc.; `detect_injection(query) -> bool`.
3. **`domain.py`**: `DomainGuardrail.validate(query)` runs four checks —
   length 10–500, no injection patterns (`sanitise`), Haiku binary
   classification for "is this space-science / NEO domain?", and a harm check.
   Returns `GuardrailResult`; failures short-circuit before any API calls.
4. **`factcheck.py`**: `build_grounding_context(...)` flattens all agent outputs
   into a single source-of-truth dict; `FactCheckLayer.check(report, grounding)`
   extracts numbers via regex, matches each to a grounding value, flags >5%
   deviation, and writes results into `confidence_notes` (never deletes claims).
5. **`token_budget.py`**: `TokenBudgetGuardrail` with `MAX_TOKENS_PER_AGENT=4096`,
   warn at 70%, compress at 85% (Haiku-summarise old turns → summary + last 3),
   hard-stop with partial results at 95%. Implement `AgentContext.compress_history`.
6. **Logging**: confirm `strip_secrets` (Phase 1) also masks email patterns.
7. **Tests**: off-topic and injection queries are rejected; an inflated number in
   a report is flagged with correct `pct_diff`; budget thresholds trigger the
   right action at 70/85/95%.

### Verification checklist
- [x] Off-topic query (e.g. "best pizza recipe") is rejected with a clear reason
  (`test_off_topic_query_rejected`; FakeAnthropic returns NO).
- [x] Injection strings are caught by `sanitise.detect_injection`
  (`test_detect_injection_patterns`, and `test_injection_rejected_before_model`
  proves it short-circuits *before* the paid Haiku call — `fake.messages.calls == 0`).
- [x] A report number deviating >5% from grounding is flagged, not removed
  (`test_inflated_number_is_flagged_with_pct_diff`: 18 LD vs 12 LD → `pct_diff == 50.0`).
- [x] Compression fires at 85% and reduces `tokens_used` (assert before/after)
  (`test_compress_threshold_reduces_tokens`).
- [x] No secret or email appears in logs (regression check) — already enforced by
  `strip_secrets` (API-key + email regex); `test_strip_secrets_redacts_email`.
- [x] `mypy src/` (49 files) and `ruff check` pass clean. **65/65 unit tests** (+18).

> **Design note — where the LLM lives.** Guardrail classes own any paid call (the
> Haiku YES/NO domain classifier; the Haiku history summariser), while the data
> model stays pure: `AgentContext.compress_history(summary)` does the structural
> rewrite with the summary *handed in*, so it has zero LLM dependency and is
> trivially unit-testable. The `FactCheckLayer` is fully deterministic (regex), and
> matches each number to grounding **by unit** (`18 LD` is checked against LD
> values, never against a coincidentally-close `18.1 km/s`). Order in
> `DomainGuardrail.validate` is cheapest-first — length → injection → harm (all
> free) gate the one paid domain check, which gates the whole pipeline.

---

## Phase 6 — Orchestrator and synthesis

### Objective
Implement the `OrchestratorAgent` (Sonnet, tool-use driven, calls specialist
agents as tools, manages context + budget) and the `SynthesisAgent` (Sonnet,
grounded report generation into the `FinalReport` Pydantic schema), then prove
an end-to-end run from query → grounded report.

### Files to create
- `src/neowatch/agents/orchestrator.py` — `OrchestratorAgent`.
- `src/neowatch/agents/synthesis_agent.py` — `SynthesisAgent`.
- `src/neowatch/agents/models.py` — extend with `FinalReport`, `NEOEventReport`,
  `Citation` (alongside Phase 4 models).
- `src/neowatch/prompts/__init__.py`
- `src/neowatch/prompts/system_prompts.py` — versioned system prompts per agent.
- `src/neowatch/pipeline.py` — top-level `async run_query(query) -> FinalReport`.
- `tests/integration/test_end_to_end.py`

### Step-by-step tasks
1. **`prompts/system_prompts.py`**: versioned constants (e.g.
   `ORCHESTRATOR_V1`, `SYNTHESIS_V1`) with role, output-format, and domain
   boundaries baked in. Include version tags for system-prompt versioning.
2. **`orchestrator.py`**: `OrchestratorAgent.run()` — first runs `DomainGuardrail`;
   then a Sonnet tool-use planning loop (temp 0.2, max 2048) where each
   specialist agent is exposed as a tool. Dispatches agents, collects
   `AgentResult`s into context, checks `TokenBudgetGuardrail` between steps,
   retries failed agents via `tenacity`, logs each step with `structlog`.
3. **`agents/models.py`**: add `FinalReport` (exact spec schema:
   `executive_summary`, `neo_events`, `orbital_risk_table`, `literature_insights`,
   `confidence_notes`, `data_sources`, `images`), `NEOEventReport`, `Citation`.
4. **`synthesis_agent.py`**: `SynthesisAgent.run()` builds `GroundingContext`,
   calls Sonnet (temp 0.4, max 4096) constrained to the grounding JSON, parses
   output into `FinalReport`, then runs `FactCheckLayer` and writes flags into
   `confidence_notes`.
5. **`pipeline.py`**: `run_query(query)` orchestrates guardrail → orchestrator →
   synthesis → factcheck and returns a validated `FinalReport`.
6. **Test**: end-to-end integration test (live keys, marked) runs the example
   spec query and asserts a well-formed `FinalReport` with citations.

### Verification checklist
- [x] Orchestrator rejects off-topic queries before any agent/API call
  (`test_rejects_off_topic_before_any_agent`: stub agents `calls == 0`, only the
  guardrail classification ran — `fake.messages.calls == 1`).
- [x] Orchestrator invokes only the agents a given query needs, not always all 4
  (`test_invokes_only_needed_agents`: plan calls fetch only → `data == ["fetch_neo_data"]`,
  other three stubs idle).
- [x] `SynthesisAgent` output validates against `FinalReport` with no parse errors
  (`test_synthesis_builds_valid_final_report`; plus `test_malformed_prose_does_not_crash`
  proves a non-JSON model reply still yields a valid report).
- [x] FactCheck flags surface in `confidence_notes` on a deliberately wrong number
  (`test_wrong_number_surfaces_in_confidence_notes`: "99 LD" vs computed 12 LD).
- [x] `run_query(<spec example query>)` returns a report with ≥1 citation + risk row
  (live `tests/integration/test_end_to_end.py`, gated by `NEOWATCH_RUN_INTEGRATION`;
  offline rejection path covered by `test_pipeline.py`).
- [x] Token budget enforced between planning steps (`budget.enforce` each loop;
  thresholds themselves covered by Phase 5 `test_token_budget.py`).
- [x] `mypy src/` clean (49 files), `ruff` clean, **71/71 unit tests** (+6).

### Open decision — RESOLVED
- **Specialist agents as Claude "tools" vs. direct calls.** Resolved in favour of
  the spec's **real Sonnet tool-use loop**: each agent is a Claude tool, Sonnet
  decides which to call. This is the project's core agentic lesson, so we paid the
  extra planning tokens for it — but bounded the cost with a hard 6-iteration cap, a
  `TokenBudgetGuardrail.enforce` between every step, and minimal (empty) tool input
  schemas so Sonnet decides *whether* to call, not low-level args. The trade-off vs.
  a hard-coded sequence is documented in `orchestrator.py`'s module docstring.

> **Design note — deterministic core extends into synthesis.** Sonnet writes only
> *prose* (executive summary, literature insights, one sentence per event); every
> number, risk-table row, and citation in the `FinalReport` is assembled in Python
> from CalcAgent's computed figures. That keeps `FactCheckLayer` meaningful — it
> audits exactly the text the model authored — and means a hallucinated figure can
> only ever land in a flagged note, never in the tables. Prose JSON parsing is
> best-effort: a non-JSON reply degrades to empty prose, never a crash.

---

## Phase 7 — Gradio UI

### Objective
Build the Gradio chat interface that accepts a query, streams progress as agents
run, and renders the `FinalReport` as markdown narrative + a risk table +
embedded images + a source appendix.

### Files to create
- `src/neowatch/ui/__init__.py`
- `src/neowatch/ui/app.py` — Gradio `Blocks` interface.
- `src/neowatch/ui/render.py` — `FinalReport` → markdown/table/image renderers.
- `src/neowatch/main.py` — update entry point to launch the UI on `:7860`.
- `tests/unit/test_render.py`

### Step-by-step tasks
1. **`ui/render.py`**: pure functions converting a `FinalReport` into a markdown
   string (executive summary + literature insights + confidence notes), a
   dataframe for `orbital_risk_table`, an image gallery list, and a citations
   appendix. No side effects — easy to unit-test.
2. **`ui/app.py`**: a `gr.Blocks` app with a query textbox, a submit button, a
   progress/status area, a markdown report pane, a `gr.Dataframe` risk table,
   and a `gr.Gallery`. The submit handler calls `pipeline.run_query` and streams
   status updates as agents complete.
3. **`main.py`**: `main()` builds the app and calls `.launch(server_port=7860)`.
4. **Test**: `test_render.py` feeds a fixture `FinalReport` and asserts the
   markdown/table/gallery outputs contain expected fields.

### Verification checklist
- [x] `python -m neowatch.main` launches a Gradio server at `localhost:7860`
  (verified: `build_app().launch(server_port=7860)` serves **HTTP 200** on `/`).
- [x] Submitting a query renders narrative + risk table + image(s) — renderers are
  pure and unit-tested (`test_render.py`); a live submit (real report) needs API
  keys and is a manual check.
- [x] Progress indicator updates as each agent completes — `pipeline.run_query`
  takes a `progress` hook; the orchestrator emits per-agent events that the Gradio
  handler streams via an `asyncio.Queue` (producer/consumer).
- [x] An off-topic query shows the guardrail rejection message (no crash) —
  `run_query` returns a valid rejection `FinalReport` (`test_pipeline.py`), which
  `report_to_markdown` renders; the UI handler also wraps the run in try/except.
- [x] `mypy src/` (49 files) and `ruff check` pass clean over `ui/`.
- [x] `pytest tests/unit/test_render.py` passes (4 tests; **75/75** total).

> **Design note — streaming over a single `await`.** `run_query` is one long
> coroutine, so the UI can't see inside it. To surface per-agent progress, the
> Gradio handler runs the pipeline as a background task and drains an
> `asyncio.Queue` the pipeline pushes status strings onto — a classic
> producer/consumer. The handler is an async generator, so each queue message
> becomes a UI update and the final yield carries the real report. The renderers in
> `ui/render.py` are deliberately pure (no Gradio types), so they unit-test without
> a server; `app.py` is the only Gradio-coupled module.

---

## Phase 8 — Production hardening

### Objective
Make the system shippable: comprehensive unit + integration test coverage, a
working Dockerfile, HuggingFace Spaces deployment artifacts, a README with
setup/run/deploy instructions, and a demo capture.

### Files to create
- `Dockerfile`
- `app.py` (repo root) — HF Spaces entry wrapper importing `neowatch.main`.
- `requirements.txt` (root — already created during scaffold; verify/freeze).
- `.dockerignore`
- `README.md`
- `tests/conftest.py` — shared fixtures (mock clients, sample `FinalReport`).
- `tests/integration/test_smoke.py` — minimal end-to-end smoke test.
- `.github/workflows/ci.yml` — lint + type-check + unit tests on push (optional).
- `docs/DEMO.md` — placeholder for the demo gif + screenshots.

### Step-by-step tasks
1. **`conftest.py`**: fixtures for `Settings` (test keys), mocked data clients,
   and a canned `FinalReport` to decouple UI/synthesis tests from live APIs.
2. **Coverage**: fill unit gaps so each module has at least happy-path + one
   failure-path test; ensure integration tests are `@pytest.mark.integration`
   and skipped without keys.
3. **`Dockerfile`**: `python:3.11-slim`, copy `requirements.txt`, install,
   copy `src/`, `CMD ["python", "-m", "neowatch.main"]` (per spec §11).
4. **`app.py` (root)**: thin wrapper so HF Spaces' Gradio SDK finds the entry
   point; imports and runs `neowatch.main.main()`.
5. **`.dockerignore`**: exclude `.venv`, `.chroma`, `tests`, `__pycache__`, `.env`.
6. **`README.md`**: overview, architecture diagram reference, setup, env vars,
   run, test, Docker, and HF Spaces deploy instructions; link the AI-engineering
   goals table from the spec.
7. **`ci.yml`** (optional): run `ruff`, `mypy`, `pytest tests/unit` on push.
8. **`DEMO.md`**: capture a run of the example query; embed gif/screenshots.

### Verification checklist
- [x] `pytest tests/ -v` → all non-integration tests pass (**76**, incl. the offline
  `tests/integration/test_smoke.py`; live integration tests skip without keys).
- [x] `mypy src/` (49 files) and `ruff check src/ tests/` → clean across the repo.
- [~] `docker build -t neowatch .` — **Dockerfile written & reviewed; not yet built**
  in this session (the local Docker daemon was not running). `python -m neowatch.main`
  is verified to serve HTTP 200, and the image is standard `python:3.12-slim` +
  `requirements.txt` + `pip install -e .`. Run `docker build -t neowatch .` once
  Docker Desktop is up to tick this.
- [x] HF Spaces deploy: `app.py` + `requirements.txt` at root; secrets documented in
  the README ("Deploy to HuggingFace Spaces").
- [x] README enables clone → running UI (setup, env vars, run, test, Docker, deploy).
- [x] ChromaDB re-ingests cleanly on a fresh start — no volume assumed; `.dockerignore`
  excludes `.chroma/`, and `RAGAgent` ingests when the store `is_stale()`.
- [~] Demo artifact — `docs/DEMO.md` placeholder with capture instructions committed;
  the GIF/screenshots need a live keyed run in a browser (manual).

> **Deviations from spec, noted:** base image is `python:3.12-slim` (not 3.11) to
> match `requires-python = ">=3.12"`; added `libgomp1` for onnxruntime; set
> `GRADIO_SERVER_NAME=0.0.0.0` so the UI is reachable inside the container.

---

## Cross-phase definition of done

A phase is complete only when **all** of the following hold:

1. Every checklist box in the phase is ticked.
2. `ruff check src/ tests/` — zero errors.
3. `mypy src/` — zero errors.
4. `pytest tests/ -v --tb=short` — all (non-skipped) tests pass.
5. No `print()` / bare `logging` / hardcoded secret introduced.
6. New public classes/methods have Google-style docstrings and full type hints.
7. **Learning mode honoured:** each step was narrated *What / Why / Trade-offs /
   Tools* in chat, and a short entry for the phase was appended to
   `docs/LEARNING_LOG.md`.
