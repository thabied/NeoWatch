"""HuggingFace Spaces entry point.

Spaces' Gradio SDK runs ``app.py`` at the repo root and launches the ``demo``
object it finds here. This is a thin wrapper: it configures logging and builds the
app from :mod:`neowatch.ui.app`, keeping all real logic inside the package.

Locally you can also run the app via ``python -m neowatch.main`` (which launches
on a fixed port); this file exists specifically for the Spaces convention.

Required Space secrets: ``ANTHROPIC_API_KEY`` and ``NASA_API_KEY``.
"""

from __future__ import annotations

from neowatch.config import get_settings
from neowatch.logging_config import configure_logging
from neowatch.ui.app import build_app

configure_logging(get_settings().log_level)
demo = build_app()

if __name__ == "__main__":
    demo.launch()
