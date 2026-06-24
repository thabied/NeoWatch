"""Report rendering.

Pure functions that turn a ``FinalReport`` into UI-ready pieces: a markdown
string (summary + insights + confidence notes), a dataframe for the risk table,
a gallery list for images, and a citations appendix.

Key concept: keeping rendering side-effect-free (separate from the Gradio
wiring) makes it unit-testable without launching a server.

Implemented in Phase 7.
"""
