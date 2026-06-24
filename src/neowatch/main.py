"""Application entry point.

Run with ``python -m neowatch.main`` to launch the Gradio web UI on port 7860.
It configures logging, logs a startup line, builds the app, and launches the
server.
"""

from __future__ import annotations

import structlog

from neowatch import __version__
from neowatch.config import get_settings
from neowatch.logging_config import configure_logging
from neowatch.ui.app import build_app

_SERVER_PORT = 7860


def main() -> None:
    """Configure logging, then build and launch the NeoWatch web UI."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger("neowatch")
    logger.info(
        "neowatch.startup",
        version=__version__,
        haiku_model=settings.haiku_model,
        sonnet_model=settings.sonnet_model,
        log_level=settings.log_level,
        port=_SERVER_PORT,
    )
    app = build_app()
    app.launch(server_port=_SERVER_PORT)


if __name__ == "__main__":
    main()
