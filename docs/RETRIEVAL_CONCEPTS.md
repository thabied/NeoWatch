# Retrieval Concepts — taught through NeoWatch

An evergreen primer on the RAG-retrieval topics every AI engineer is expected to
reason about — ranking, re-ranking, cosine similarity, hybrid search, and the
accuracy-vs-speed trade-off — mapped onto **what NeoWatch actually does** in its
Phase 3 RAG pipeline. Each section says: the concept, where (or whether) NeoWatch
uses it, and how you would extend it.

> TL;DR of coverage:
> - **Implemented:** dense (cosine) retrieval, sparse (BM25) ranking, a two-stage
>   recall→re-rank funnel, chunking + overlap, dedup.
> - **Deliberately skipped:** cross-encoder re-ranking, true score fusion (RRF),
>   retrieval evaluation metrics, ANN index tuning, query transformation.
> - The skips are fine for a small (~80-paper) corpus; this doc explains the
>   *reasoning*, which is the actual skill.

---

## 0. The mental model: retrieval is a funnel

You never score the whole corpus with your most expensive method. You **cascade**
from cheap+broad to expensive+precise:

```
            whole corpus (N chunks)
                    │   cheap, recall-oriented
                    ▼
   Stage 1: dense ANN search  ── top 20 candidates
                    │   more expensive, precision-oriented
                    ▼
   Stage 2: re-rank           ── top 5 final results
                    │
                    ▼
              synthesis (LLM)
```

This single picture explains the **accuracy-vs-speed trade-off**: Stage 1 must be
fast over *everything* (so you accept approximate, recall-focused), Stage 2 can be
slow because it only sees ~20 items (so you spend compute to maximize precision).

**NeoWatch:** `retrieve(keywords, top_k=5)` does exactly this — cosine search for
top-20, BM25 re-rank down to top-5.

---

## 1. Embeddings & the vector space

Text is mapped to a **384-dimensional vector** by `all-MiniLM-L6-v2`. The model is
trained (contrastive learning) so that *semantically similar* text lands close
together. Retrieval is then just "find the nearest vectors to the query vector."

Key things an engineer must hold:
- The dimension (384 here) is fixed by the model; it defines the geometry.
- **Embeddings are a versioned data contract.** Vectors from different models — or
  even different versions of the same model — are **not comparable**. Change the
  embedding model and you must **re-index the entire corpus**. Treat a model swap
  like a database schema migration.

---

## 2. Cosine similarity (the distance metric)

Cosine similarity measures the **angle** between two vectors, ignoring their
magnitude:

```
cos(a, b) = (a · b) / (‖a‖ · ‖b‖)        range: −1 … 1  (1 = identical direction)
```

Why cosine (not raw dot product or Euclidean) for text embeddings?
- **Magnitude-invariant:** a long document and a short one about the same topic
  point the *same direction* even if one vector is "longer." We care about
  *direction* (meaning), not *length*.
- If vectors are **L2-normalized** (‖v‖ = 1), cosine, dot product, and Euclidean
  all produce the **same ranking** — which is why normalized-embedding stores
  often default to L2 internally yet behave like cosine.

**NeoWatch / practical note:** ChromaDB's default distance is L2 (squared
euclidean). To get true cosine semantics, configure the collection with
`metadata={"hnsw:space": "cosine"}` at creation — a real implementation detail
that bites people who assume "vector DB = cosine."

---

## 3. Approximate Nearest Neighbor (ANN) — the "speed" lever

Exact nearest-neighbor search is **O(N)** per query (compare against every chunk).
That's fine for 80 papers, fatal for 80 million. Vector DBs use **ANN indexes** —
ChromaDB uses **HNSW** (Hierarchical Navigable Small World): a graph you can walk
in roughly **logarithmic** time, trading a small, tunable amount of recall for a
huge speed gain.

The accuracy/speed knobs (HNSW):
- `ef` / `ef_search` — how many candidates to explore at query time. Higher = more
  accurate, slower.
- `M` — graph connectivity. Higher = better recall, more memory.

**NeoWatch:** uses HNSW **defaults** (the corpus is tiny, so tuning buys nothing).
"Not tuning it" is the *correct* decision here — but you should be able to say *why*.

---

## 4. Dense vs. sparse retrieval (and why hybrid exists)

This is the heart of the topic.

| | **Dense** (embeddings, cosine) | **Sparse** (BM25, lexical) |
|---|---|---|
| Matches on | **meaning** / semantics | **exact terms** / tokens |
| Great at | synonyms, paraphrase, "fuzzy" intent | rare jargon, IDs, names, exact phrases |
| Weak at | exact rare tokens it never saw clearly | paraphrase, synonyms |
| Example win | "asteroid danger scale" → finds *Torino scale* | "2009 JR5" → finds that exact designation |

**BM25** (sparse) is a refined TF-IDF: it scores documents by term overlap with the
query, with saturation (more occurrences help less and less) and length
normalization. It has **no notion of meaning** — but it's unbeatable for exact rare
tokens, which is *exactly* the kind of thing NEO research is full of (object
designations, scale names, instrument acronyms).

Dense and sparse fail in **opposite** ways, so combining them ("**hybrid**") covers
both. That's the whole motivation.

**NeoWatch:** hybrid by **cascade** — dense for broad recall (top-20), BM25 to
re-order by lexical relevance (top-5). It gets both signals.

---

## 5. Re-ranking — a taxonomy

"Re-ranking" = take Stage-1 candidates and reorder them with a better (slower)
signal. There's a ladder of options, cheap → expensive:

1. **Lexical re-rank (BM25)** — cheap, no model, great for exact terms.
   **← NeoWatch uses this.**
2. **Cross-encoder re-rank** — a transformer that reads `(query, document)`
   *together* and outputs a relevance score. Far more accurate than comparing two
   independently-made embeddings ("bi-encoder"), because it sees the interaction.
   Cost: one model forward-pass *per candidate* → slow, and it needs `torch`.
   **Not in NeoWatch** — would reintroduce the heavy ML stack for marginal gain on
   an 80-paper corpus. *How you'd add it:* run a `cross-encoder/ms-marco-MiniLM`
   over the top-20 before truncating to top-5.
3. **LLM re-rank** — ask an LLM to score/order candidates. Most flexible, most
   expensive, highest latency. (NeoWatch's *synthesis* LLM implicitly judges
   relevance when it writes the answer, but it isn't a formal re-ranker.)

The lesson: re-rankers trade **latency and dependency weight for precision**. You
climb the ladder only when measurement shows you need to.

---

## 6. Cascade vs. fusion (a precise distinction worth knowing)

NeoWatch does a **cascade**: dense *filters*, then BM25 *reorders* the survivors.
The dense stage gets the final say on *which* documents survive.

True **hybrid fusion** is different: run dense **and** sparse over the corpus
*independently*, get two ranked lists, then **merge** them. The standard merge is
**Reciprocal Rank Fusion (RRF)**:

```
score(d) = Σ over lists  1 / (k + rank_in_list(d))     # k ≈ 60 by convention
```

RRF needs no score calibration (it uses *ranks*, not raw scores), which is why it's
the default in many production hybrid systems.

**Trade-off:** cascade is simpler and cheaper but can't recover a document that the
dense stage missed entirely (BM25 never sees it). Fusion catches "dense missed it
but lexical found it" cases — at the cost of running both retrievers fully.
NeoWatch chooses cascade for simplicity; on a larger/term-heavy corpus you'd
likely move to RRF fusion.

---

## 7. Chunking — upstream of all retrieval quality

You don't embed whole documents; you embed **chunks**. Chunk size is a trade-off:
- **Too large:** the embedding averages many ideas → diluted, fuzzy vector;
  retrieval gets "vaguely related" hits.
- **Too small:** precise vectors but fragmented context; an answer may span chunks.
- **Overlap** (sliding window) keeps ideas that straddle a boundary retrievable.

**NeoWatch:** ~512-token windows with 50-token overlap over arXiv abstracts.
(Abstracts are already short and dense, so this is gentle chunking.)

The meta-lesson: **garbage chunking caps your ceiling.** No re-ranker fixes a
chunk that split a key sentence in half.

---

## 8. Evaluation — the biggest gap, and the most important habit

NeoWatch has **no retrieval evaluation harness**, and that's the gap most worth
naming, because **you cannot improve what you don't measure.** The standard metrics:

- **Recall@k** — of the truly relevant docs, what fraction appear in the top-k?
  (Did we *retrieve* the answer at all? Stage-1's job.)
- **Precision@k** — of the top-k, what fraction are relevant? (Stage-2's job.)
- **MRR (Mean Reciprocal Rank)** — 1/rank of the first relevant doc, averaged.
  Rewards putting the right answer *first*.
- **nDCG** — graded relevance with position discounting; the gold standard when
  "relevant" isn't binary.

*How you'd add it to NeoWatch:* hand-label ~10 queries with their relevant
arXiv IDs, then compute recall@5 / MRR after `retrieve()`. With that harness you
could *measure* whether adding a cross-encoder or switching to RRF actually helps —
turning the choices in this doc from opinion into data.

---

## 9. What this teaches about engineering judgment

NeoWatch's retrieval is deliberately **mid-spectrum**: more than naive single-vector
search, less than a tuned production hybrid. The defensible reasoning:

- Corpus is small (~80 papers) → ANN tuning and fusion buy little.
- Term-heavy domain → BM25 re-rank earns its place (cheap, high value).
- Cross-encoders/eval harnesses are real work → adopt them when a **measured** need
  appears, not preemptively.

That "right-sized for the problem, with a clear story for what you'd add next" is
exactly the judgment the canonical RAG tutorials are trying to build. The pieces
NeoWatch skips aren't gaps in your knowledge — they're the **next moves you can
articulate**, which is the goal.
