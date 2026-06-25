"""HuggingFace Spaces entry point.

Spaces' Gradio SDK runs ``app.py`` at the repo root and launches the ``demo``
object it finds here. This is a thin wrapper: it configures logging and builds the
app from :mod:`neowatch.ui.app`, keeping all real logic inside the package.

Locally you can also run the app via ``python -m neowatch.main`` (which launches
on a fixed port); this file exists specifically for the Spaces convention.

Required Space secrets: ``ANTHROPIC_API_KEY`` and ``NASA_API_KEY``.
"""

from __future__ import annotations

from pathlib import Path

from neowatch.config import get_settings
from neowatch.logging_config import configure_logging
from neowatch.ui.app import build_app

_settings = get_settings()
configure_logging(_settings.log_level)
demo = build_app()

# Gradio 4+ only serves local files from its allow-list, so the resized APOD
# images need their cache dir explicitly permitted or the gallery renders blank.
_ALLOWED_PATHS = [str(Path(_settings.image_cache_dir).resolve())]

if __name__ == "__main__":
    demo.launch(allowed_paths=_ALLOWED_PATHS)
