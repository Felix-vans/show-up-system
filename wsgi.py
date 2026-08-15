"""Server entrypoint, used by gunicorn:

    gunicorn --workers 2 --bind 0.0.0.0:5000 wsgi:app

Importing this module prepares the database, starts logging, and starts the
background scheduler. The scheduler protects itself with a file lock, so it
is safe to run several gunicorn workers: only one of them ends up sending
the reminders.
"""

from dotenv import load_dotenv

load_dotenv()

from app import app  # noqa: E402  (must come after load_dotenv)
from db import init_db  # noqa: E402
from logging_config import setup_logging  # noqa: E402
from scheduler import start_scheduler  # noqa: E402

setup_logging()
init_db()
start_scheduler()

__all__ = ["app"]
