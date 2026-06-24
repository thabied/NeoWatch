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
