"""The watch loop — NeoWatch's recurring, stateful *outer* loop.

Where the orchestrator (``neowatch.agents.orchestrator``) is an *inner* tool-use
loop that runs many steps inside one user query, this package is the *outer*
loop: one cheap deterministic pass repeated across time. It periodically senses
each watchable science domain, diffs the fresh reading against the last
persisted baseline, and raises alerts on the transitions that matter.

Two engineering themes live here (the companions to the context-engineering work
documented across ``docs/``):

- **Loop engineering** — cadence, edge- vs level-triggering, hysteresis, and the
  idempotency that makes a repeated tick converge instead of spamming.
- **Harness engineering** — state that survives outside the context window: a
  durable, atomically-written store, an idempotent tick, and a clean split
  between *policy* (what/when to check) and *mechanism* (who invokes the tick).

Phase A ships only the harness substrate: ``models`` (the persisted shapes) and
``store`` (the durable, crash-safe file store). Sensing, rules, and the loop
itself arrive in later phases.
"""

from __future__ import annotations
