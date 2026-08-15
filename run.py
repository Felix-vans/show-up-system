"""Local development entrypoint (Windows / your own laptop).

On the server the app runs under gunicorn via wsgi.py instead — see
DEPLOY.md. This file stays because it is the convenient way to run the
app locally with a double-click.
"""

import os

from dotenv import load_dotenv

from app import app
from db import init_db
from logging_config import setup_logging
from scheduler import start_scheduler

load_dotenv()


def main() -> None:
    setup_logging()
    init_db()
    scheduler = start_scheduler()

    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))

    banner = (
        "\n"
        + "=" * 60
        + "\n  ORYN SHOW-UP SYSTEM (lokaal)\n"
        + "=" * 60
        + f"\n  Open:  http://localhost:{port}\n"
        + "  Server MOET blijven draaien voor reminders.\n"
        + "  Stop:  Ctrl+C\n"
        + "=" * 60
        + "\n"
    )
    print(banner)

    try:
        app.run(host=host, port=port, debug=False, use_reloader=False)
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
