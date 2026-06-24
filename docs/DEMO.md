# NeoWatch — Demo

> **Placeholder.** The demo capture (GIF + screenshots) needs a live run with real
> API keys in a browser, so it is captured manually rather than generated. This
> file is the slot for those artifacts; replace the placeholders below after a run.

## How to capture

1. Put real keys in `.env` (`ANTHROPIC_API_KEY`, `NASA_API_KEY`).
2. Launch the UI: `python -m neowatch.main` → open <http://localhost:7860>.
3. Run the example query:
   _"Which near-Earth asteroids approach Earth this week, and how risky are they?"_
4. Record the screen (e.g. macOS `⇧⌘5`, or [Kap](https://getkap.co/)) while the
   progress pane streams and the report renders. Export a GIF.
5. Grab a still of the finished report (narrative + risk table + gallery).

## Artifacts

<!-- Replace these with the captured files committed under docs/ -->

![NeoWatch run (GIF)](demo.gif)

![Finished report (screenshot)](report.png)

## What the demo should show

- The **progress pane** streaming per-agent status (`Validating query…`,
  `Running fetch_neo_data…`, `Running analyze_orbits…`, `Writing report…`).
- A rendered **executive summary** plus per-event bullets.
- The **orbital risk table** (miss distance / velocity / size / risk band).
- An **image gallery** with NASA/APOD attribution.
- A **Sources** appendix with at least one citation.
- An **off-topic query** (e.g. "best pizza recipe") returning the guardrail
  rejection message instead of crashing.
