"""User profiles + resolving which mailbox sends a given user's email.

Design note — why credentials are NOT in users.json anymore:

Today all three sellers send through ONE shared mailbox (configured in .env
as SMTP_ADDRESS / SMTP_PASSWORD), because the per-person business addresses
aren't ready yet. Each seller still keeps their own identity: the prospect
sees "Jules" as the sender name and Jules' signature in the mail body.

When the business emails do arrive, you have two options and neither
requires a code change:

  1. Everyone on one business mailbox -> just change SMTP_ADDRESS and
     SMTP_PASSWORD in .env. Done.
  2. Everyone on their own mailbox -> add "smtp_address" and
     "smtp_password" to that person's entry in users.json. A per-user value
     always wins over the shared .env one.

Keeping secrets out of users.json also means users.json is safe to commit
to git, while .env stays private.
"""

import json
import os
from pathlib import Path
from typing import Optional

_BASE = Path(__file__).parent

# users.json lives at the project root (safe to commit — no secrets).
# The old location inside data/ is still honoured so existing installs
# keep working after an update.
_ROOT_PATH = _BASE / "users.json"
_LEGACY_PATH = _BASE / "data" / "users.json"

_PLACEHOLDER_PREFIXES = ("REPLACE_ME", "VUL_IN", "CHANGE_ME")


def users_path() -> Path:
    if _ROOT_PATH.exists():
        return _ROOT_PATH
    return _LEGACY_PATH


def load_users() -> list[dict]:
    """Load all user profiles. Raises if the file is missing."""
    path = users_path()
    if not path.exists():
        raise FileNotFoundError(
            f"users.json not found at {_ROOT_PATH}. "
            f"Copy users.example.json to users.json and edit it."
        )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("users", [])


def get_user(user_id: str) -> Optional[dict]:
    """Return the user dict for a given id, or None if not found."""
    for u in load_users():
        if u["id"] == user_id:
            return u
    return None


def _clean(value: Optional[str]) -> str:
    """Strip a value, treating obvious placeholders as empty."""
    v = (value or "").strip()
    if not v or v.startswith(_PLACEHOLDER_PREFIXES):
        return ""
    return v


def sender_for(user: dict) -> dict:
    """Resolve which mailbox sends this user's email.

    Order: the user's own smtp_* fields, then the legacy gmail_* fields
    (so old users.json files keep working), then the shared .env mailbox.
    The display name is always the user's own name.
    """
    address = (
        _clean(user.get("smtp_address"))
        or _clean(user.get("gmail_address"))
        or _clean(os.getenv("SMTP_ADDRESS"))
    )
    password = (
        _clean(user.get("smtp_password"))
        or _clean(user.get("gmail_password"))
        or _clean(os.getenv("SMTP_PASSWORD"))
    )
    return {
        "address": address,
        "password": password,
        "name": user.get("name", "Oryn"),
    }


def is_configured(user: dict) -> bool:
    """True if we can actually send mail as this user."""
    s = sender_for(user)
    return bool(s["address"] and s["password"])


def notify_address_for(user: dict) -> str:
    """Where this user's own notifications (digest / pings) should land.

    Falls back to the sending mailbox when the user has no personal
    address configured yet — relevant while everyone shares one inbox.
    """
    return _clean(user.get("notify_email")) or sender_for(user)["address"]
