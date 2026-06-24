"""Gradio app.

Builds the ``gr.Blocks`` interface: query textbox, submit button, progress/status
area, markdown report pane, risk-table dataframe, and image gallery. The submit
handler calls ``pipeline.run_query`` and streams status as each agent completes.

Key concept: the UI is a thin shell over ``pipeline.run_query`` — all real logic
lives behind that one call. The only interesting piece here is *streaming*: the
pipeline is one long ``await``, so to surface per-agent progress we run it as a
background task and drain a queue the pipeline pushes status strings onto
(producer/consumer with ``asyncio.Queue``). The handler is an async generator, so
each queue message becomes a UI update; the final yield carries the real report.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import gradio as gr
import pandas as pd

from ..agents.models import FinalReport
from ..pipeline import run_query
from .render import gallery_items, report_to_markdown, risk_table_dataframe

_EXAMPLE_QUERY = "Which near-Earth asteroids approach Earth this week, and how risky are they?"


async def handle_query(query: str) -> AsyncIterator[tuple[str, str, pd.DataFrame, list[Any]]]:
    """Stream status updates while the pipeline runs, then yield the final report.

    Yields a 4-tuple matching the output widgets: (status, report markdown, risk
    dataframe, gallery items). During processing the report/table/gallery are
    empty placeholders; the last yield fills them in.
    """
    empty = FinalReport(query=query or "")
    if not query or not query.strip():
        yield "Enter a question to begin.", "", risk_table_dataframe(empty), []
        return

    # The pipeline pushes progress strings here; the loop below drains them.
    updates: asyncio.Queue[str] = asyncio.Queue()
    task = asyncio.create_task(run_query(query, progress=updates.put_nowait))

    statuses: list[str] = []
    while not task.done() or not updates.empty():
        try:
            message = await asyncio.wait_for(updates.get(), timeout=0.2)
        except TimeoutError:
            continue
        statuses.append(message)
        yield _status_md(statuses, done=False), "", risk_table_dataframe(empty), []

    try:
        report = await task
    except Exception as exc:  # noqa: BLE001 — show failures in the UI, never crash it
        yield f"⚠️ Something went wrong: {exc}", "", risk_table_dataframe(empty), []
        return

    statuses.append("Done.")
    yield (
        _status_md(statuses, done=True),
        report_to_markdown(report),
        risk_table_dataframe(report),
        gallery_items(report),
    )


def _status_md(statuses: list[str], done: bool) -> str:
    """Render the running status list as a small markdown checklist."""
    marker = "✅" if done else "⏳"
    lines = [f"{marker} {s}" for s in statuses]
    return "  \n".join(lines)


def build_app() -> gr.Blocks:
    """Construct (but do not launch) the Gradio Blocks interface."""
    with gr.Blocks(title="NeoWatch") as demo:
        gr.Markdown(
            "# 🛰️ NeoWatch\n"
            "Ask about near-Earth objects — approaches, risk, the science, or imagery. "
            "Every number is computed deterministically and fact-checked; the model only "
            "writes the prose."
        )
        with gr.Row():
            query = gr.Textbox(
                label="Your question",
                placeholder=_EXAMPLE_QUERY,
                scale=4,
            )
            submit = gr.Button("Research", variant="primary", scale=1)
        gr.Examples(examples=[_EXAMPLE_QUERY], inputs=query)

        status = gr.Markdown(label="Progress")
        report_md = gr.Markdown(label="Report")
        risk_table = gr.Dataframe(label="Orbital risk table", wrap=True)
        gallery = gr.Gallery(label="Imagery", columns=3, height="auto")

        outputs = [status, report_md, risk_table, gallery]
        submit.click(fn=handle_query, inputs=query, outputs=outputs)
        query.submit(fn=handle_query, inputs=query, outputs=outputs)

    demo.queue()  # required for streaming generator handlers
    # `with gr.Blocks() as demo` yields Any from gradio's context manager; we know
    # it's a Blocks, so cast to keep the public return type honest under --strict.
    return cast("gr.Blocks", demo)
