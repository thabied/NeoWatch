"""Gradio app.

Builds the ``gr.Blocks`` interface: query textbox, submit button, progress/status
area, markdown report pane, risk-table dataframe, and image gallery. The submit
handler calls ``pipeline.run_query`` and streams status as each agent completes.

Key concept: the UI is a thin shell over ``pipeline.run_query`` — all real logic
lives behind that one call.

Implemented in Phase 7.
"""
