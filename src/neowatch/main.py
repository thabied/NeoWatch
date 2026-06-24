"""Application entry point.

Run with ``python -m neowatch.main``. In Phase 1 this builds settings and
configures logging to prove the scaffold wires together; in Phase 7 it launches
the Gradio web UI on port 7860.
"""

from __future__ import annotations

import structlog

from neowatch import __version__
from neowatch.config import get_settings
from neowatch.logging_config import configure_logging


def main() -> None:
    """Build settings, configure logging, and emit a startup line.

    This is intentionally minimal in Phase 1: its job is to confirm config and
    logging are correctly wired before any agents exist.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger("neowatch")
    logger.info(
        "neowatch.startup",
        version=__version__,
        haiku_model=settings.haiku_model,
        sonnet_model=settings.sonnet_model,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
