"""Timezone conversion and Dutch date formatting helpers."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BRUSSELS_TZ = ZoneInfo("Europe/Brussels")

DUTCH_DAYS = [
    "maandag", "dinsdag", "woensdag", "donderdag",
    "vrijdag", "zaterdag", "zondag",
]

DUTCH_MONTHS = [
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]


def brussels_to_utc(local_dt_str: str) -> str:
    """Convert 'YYYY-MM-DDTHH:MM' (Brussels local time) to UTC ISO string."""
    local_dt = datetime.fromisoformat(local_dt_str).replace(tzinfo=BRUSSELS_TZ)
    utc_dt = local_dt.astimezone(timezone.utc)
    return utc_dt.isoformat()


def utc_to_brussels(utc_iso: str) -> datetime:
    """Return a Brussels-timezone datetime from a UTC ISO string."""
    utc_dt = datetime.fromisoformat(utc_iso)
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(BRUSSELS_TZ)


def format_dutch(dt: datetime) -> str:
    """Format as 'maandag 12 juli om 14:00'."""
    day_name = DUTCH_DAYS[dt.weekday()]
    month_name = DUTCH_MONTHS[dt.month - 1]
    return f"{day_name} {dt.day} {month_name} om {dt.strftime('%H:%M')}"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
