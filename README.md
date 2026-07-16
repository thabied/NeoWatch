# 🛰️ NeoWatch

**An agentic Near-Earth Object (NEO) research system.** Ask a natural-language
question about asteroids and comets approaching Earth — NeoWatch fetches live NASA
data, computes the orbital and risk figures in deterministic code, retrieves
relevant scientific literature, and writes a grounded, fact-checked report with an
image gallery and citations.

> **Design principle: deterministic core, LLM shell.** The language model never
> produces a number. Every figure (miss distance, velocity, size, risk band) is
> computed in pure Python and *verified* against the model's prose before you see
> it. The LLM plans which data to gather and writes the narrative; it does not
> invent facts.

---

## What it does

Given a query like _"Which near-Earth asteroids approach Earth this week, and how
risky are they?"_, NeoWatch produces a report containing:

- an **executive summary** and per-object event descriptions (LLM prose, fact-checked);
- an **orbital risk table** — miss distance (lunar distances), velocity, size, risk band (all computed);
- **literature insights** drawn from retrieved arXiv papers;
- a **NASA/APOD image gallery** with attribution;
- a **sources** appendix with citations;
- **confidence notes** flagging any figure the model got wrong.

Off-topic or unsafe queries are rejected up front, cheaply.

## Architecture

```
            ┌──────────────────────── pipeline.run_query ────────────────────────┐
            │                                                                     │
  query ──▶ DomainGuardrail ──▶ OrchestratorAgent (Sonnet, tool-use loop)         │
            (length/injection/   │   chooses & dispatches specialist agents:      │
             harm/domain)        │                                                │
                                 ├─▶ FetchAgent   (Haiku) → NASA NeoWs / SBDB / …  │
                                 ├─▶ CalcAgent    (numpy core; Haiku narrates)     │
                                 ├─▶ RAGAgent     (Chroma + BM25, no LLM)          │
                                 └─▶ ImageAgent   (Pillow, no LLM)                 │
                                 │                                                │
                                 ▼                                                │
                       SynthesisAgent (Sonnet) ──▶ FactCheckLayer ──▶ FinalReport │
                       (writes prose only)         (audits numbers)               │
            └─────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                                   Gradio UI (:7860)
```

**Three guardrail layers** wrap the agents: an input `DomainGuardrail`
(length / prompt-injection / harm / domain checks, cheapest-first), an output
`FactCheckLayer` (flags any number in the prose that deviates >5% from the
computed value), and a `TokenBudgetGuardrail` (warn → compress history → hard-stop
as the budget fills).

## AI-engineering ideas demonstrated

| Idea | Where |
|---|---|
| Tool use / agentic loop | `FetchAgent` (APIs as tools), `OrchestratorAgent` (agents as tools) |
| Deterministic core, LLM shell | `calc/orbital.py` + `CalcAgent`; synthesis writes prose only |
| Model routing for cost | Haiku for specialists, Sonnet for planning/synthesis |
| RAG (dense + BM25 re-rank) | `rag/` (Chroma + ONNX MiniLM embeddings) |
| Anti-hallucination by verification | `guardrails/factcheck.py` |
| Prompt-injection & domain guarding | `guardrails/{sanitise,domain}.py` |
| Context-window / budget management | `guardrails/token_budget.py` |
| Typed contracts everywhere | Pydantic models between every layer |

A plain-English, phase-by-phase account of *why* each decision was made lives in
[`docs/LEARNING_LOG.md`](docs/LEARNING_LOG.md); the build plan is
[`docs/PLAN.md`](docs/PLAN.md); retrieval design notes are in
[`docs/RETRIEVAL_CONCEPTS.md`](docs/RETRIEVAL_CONCEPTS.md).

## Setup

Requires **Python 3.12+**.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### Environment variables

Copy the template and fill in your keys (the real `.env` is git-ignored — never
commit it):

```bash
cp .env.example .env
```

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Claude API (all agents). |
| `NASA_API_KEY` | ✅ | NASA NeoWs / APOD / DONKI / Horizons. |
| `SERP_API_KEY` | optional | Reserved for future web search. |
| `LOG_LEVEL` | optional | `INFO` (default) / `DEBUG`. |

> Get a free NASA key at <https://api.nasa.gov/> and an Anthropic key at
> <https://console.anthropic.com/>. Set a console spend limit.

## Run

```bash
python -m neowatch.main          # launches the Gradio UI on http://localhost:7860
```

### Running the watcher

NeoWatch also has a **watch loop**: a recurring, stateful pass that senses each
domain, diffs against the last run, and raises alerts on what changed. Its
decisions are fully deterministic (no LLM in the alert path). See
[`docs/WATCH_LOOP_PLAN.md`](docs/WATCH_LOOP_PLAN.md) for the design.

```bash
python -m neowatch.watch --once        # one tick, then exit (0 = no alerts, 1 = alerts fired)
python -m neowatch.watch --dry-run     # sense + diff, but persist nothing and emit nowhere
python -m neowatch.watch --interval 10800   # in-process loop: tick every 3h until Ctrl-C
```

State lives under `.watch_state/` (git-ignored): one JSON baseline per domain
plus an append-only `alerts.jsonl`. Because state is external and each tick is
idempotent, `--once` can be driven by any external scheduler (cron, GitHub
Actions, a Claude Code routine) — see
[`docs/WATCH_RUNBOOK.md`](docs/WATCH_RUNBOOK.md).

## Test

```bash
pytest tests/unit -q                              # fast, offline, zero API cost
NEOWATCH_RUN_INTEGRATION=1 pytest tests/integration -v   # live: spends tokens, hits NASA/arXiv
ruff check src/ tests/                            # lint
mypy src/                                         # type-check (strict)
```

The entire unit suite runs **offline** — agents take an injectable Anthropic
client replaced by a fake in tests, and HTTP is mocked — so it costs nothing.

## Docker

```bash
docker build -t neowatch .
docker run --rm -p 7860:7860 --env-file .env neowatch
```

Then open <http://localhost:7860>. The ChromaDB vector store is re-ingested on
first run, so no volume/persistence is required.

## Deploy to HuggingFace Spaces

1. Create a **Gradio** Space.
2. Push this repo (it has `app.py` and `requirements.txt` at the root — the entry
   points Spaces expects).
3. In **Settings → Secrets**, add `ANTHROPIC_API_KEY` and `NASA_API_KEY`.
4. The Space builds and serves the UI automatically.

## Project layout

```
src/neowatch/
  agents/      orchestrator, fetch, calc, rag, image, synthesis
  calc/        deterministic orbital/risk maths (pure numpy)
  data/        typed NASA / arXiv API clients
  guardrails/  domain, factcheck, token-budget, sanitise
  rag/         chunk, embed, store (Chroma), retrieve, ingest
  ui/          Gradio app + pure renderers
  pipeline.py  run_query(query) -> FinalReport
docs/          PLAN, LEARNING_LOG, RETRIEVAL_CONCEPTS, DEMO
tests/         unit (offline) + integration (live, gated)
```

## License

For educational use.
