"""Report rendering.

Pure functions that turn a ``FinalReport`` into UI-ready pieces: a markdown
string (summary + events + insights + confidence notes + citations appendix), a
dataframe for the risk table, and a gallery list for images.

Key concept: keeping rendering side-effect-free (separate from the Gradio wiring)
makes it unit-testable without launching a server. ``app.py`` is then a thin shell
that just hands a ``FinalReport`` to these functions and drops the results into
widgets.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..agents.models import FinalReport

# Column order for the risk dataframe (also used to build the empty frame).
_RISK_COLUMNS = ["Object", "Miss (LD)", "Velocity (km/s)", "Max size (m)", "Risk"]


def report_to_markdown(report: FinalReport) -> str:
    """Render the narrative panel: summary, events, insights, notes, citations.

    Args:
        report: The validated report from the pipeline.

    Returns:
        A single markdown string ready for a ``gr.Markdown`` pane.
    """
    parts: list[str] = [f"## Report for: _{report.query}_"]

    if report.executive_summary:
        parts.append(report.executive_summary)

    if report.neo_events:
        parts.append("### Close approaches")
        for event in report.neo_events:
            line = (
                f"- **{event.name}** — {event.miss_distance_ld:.1f} LD, "
                f"{event.velocity_km_s:.1f} km/s, up to {event.diameter_max_m:.0f} m "
                f"(risk: **{event.risk_band}**)"
            )
            if event.summary:
                line += f"\n  - {event.summary}"
            parts.append(line)

    if report.literature_insights:
        parts.append("### Literature insights")
        parts.append(report.literature_insights)

    # Generic sections contributed by non-NEO verticals (space weather, Earth
    # events…). Rendered uniformly so the UI needs no per-domain knowledge.
    for section in report.report_sections:
        parts.append(f"### {section.title}")
        if section.body_markdown:
            parts.append(section.body_markdown)
        table = _rows_to_markdown_table(section.rows)
        if table:
            parts.append(table)

    if report.confidence_notes:
        parts.append("### Confidence notes")
        parts.extend(f"- {note}" for note in report.confidence_notes)

    citations = _citations_section(report)
    if citations:
        parts.append(citations)

    return "\n\n".join(parts)


def risk_table_dataframe(report: FinalReport) -> pd.DataFrame:
    """Build the orbital-risk table as a pandas DataFrame for ``gr.Dataframe``.

    Returns an empty (but correctly-columned) frame when there are no rows, so the
    widget always has a stable shape.
    """
    rows = [
        {
            "Object": row.name,
            "Miss (LD)": round(row.miss_distance_ld, 2),
            "Velocity (km/s)": round(row.velocity_km_s, 2),
            "Max size (m)": round(row.diameter_max_m, 1),
            "Risk": row.risk_band,
        }
        for row in report.orbital_risk_table
    ]
    return pd.DataFrame(rows, columns=_RISK_COLUMNS)


def gallery_items(report: FinalReport) -> list[tuple[str, str]]:
    """Build ``(image_source, caption)`` pairs for ``gr.Gallery``.

    Prefers the locally-cached resized copy; falls back to the remote URL. The
    caption carries the attribution credit (which must always accompany the image).
    """
    items: list[tuple[str, str]] = []
    for image in report.images:
        source = image.local_path or image.url
        items.append((source, image.credit))
    return items


def _rows_to_markdown_table(rows: list[dict[str, Any]]) -> str:
    """Render a section's optional rows as a GitHub-flavoured markdown table.

    Columns are taken from the first row's keys (each section builds rows with a
    stable shape). Empty ``rows`` yields an empty string so the caller can skip it.
    """
    if not rows:
        return ""
    headers = list(rows[0].keys())
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def _citations_section(report: FinalReport) -> str:
    """Render the source appendix, or empty string when there are no sources."""
    if not report.data_sources:
        return ""
    lines = ["### Sources"]
    for citation in report.data_sources:
        label = citation.title
        if citation.identifier:
            label += f" ({citation.identifier})"
        if citation.url:
            label = f"[{label}]({citation.url})"
        lines.append(f"- {label} — _{citation.source_type}_")
    return "\n".join(lines)
