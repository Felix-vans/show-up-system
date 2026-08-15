"""Shared logging setup, used by both run.py (local) and wsgi.py (server)."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_PATH = Path(__file__).parent / "data" / "app.log"


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Rotating: caps the log at 3 x 2MB instead of growing forever.
    file_handler = RotatingFileHandler(
        LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[file_handler, logging.StreamHandler()],
    )
    # Werkzeug logs every single request — that is what ballooned the old
    # log file. Warnings and errors are still kept.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
