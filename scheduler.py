"""Background scheduler.

Three kinds of job live here:

1. The 27h reminder to the PROSPECT — always on. This one goes straight to
   the customer and needs nothing from the seller.
2. Owner notifications (the morning digest and the 1h ping) — OFF by
   default right now. All three sellers currently share one mailbox, so
   those mails would all land in the same inbox regardless of who owns the
   lead, which is just noise. The code is fully intact and switches back on
   with one line in .env once everyone has their own business address.
   Meanwhile the dashboard still shows which videos are still to send and
   which meetings are today — the seller acts on that.
3. A nightly database backup, keeping the last 7 days.

Only ONE process may run these jobs. Under gunicorn several worker
processes import this module, and without a guard each of them would fire
its own copy of every reminder — the prospect would receive the same mail
two or three times. _acquire_scheduler_lock() makes sure exactly one
process wins.
"""

import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from db import (
    DB_PATH,
    get_pending_1h_notify_reminders,
    get_pending_27h_reminders,
    get_stale_interested_leads,
    get_todays_booked_meetings,
    get_video_needed_leads,
    mark_27h_sent,
    mark_notify_sent,
)
from email_sender import render_template, send_email
from users import (
    get_user,
    is_configured,
    load_users,
    notify_address_for,
    sender_for,
)
from utils import BRUSSELS_TZ, format_dutch, utc_to_brussels

log = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "ja")


DIGEST_HOUR = int(os.getenv("DIGEST_HOUR", "7"))
DIGEST_MINUTE = int(os.getenv("DIGEST_MINUTE", "30"))
STALE_DAYS = int(os.getenv("STALE_LEAD_DAYS", "5"))

# Owner-facing notifications: parked until everyone has a personal mailbox.
DIGEST_ENABLED = _env_flag("DIGEST_ENABLED", False)
OWNER_PINGS_ENABLED = _env_flag("OWNER_PINGS_ENABLED", False)

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", DB_PATH.parent / "backups"))
BACKUP_KEEP_DAYS = int(os.getenv("BACKUP_KEEP_DAYS", "7"))
BACKUP_HOUR = int(os.getenv("BACKUP_HOUR", "3"))

_LOCK_PATH = DB_PATH.parent / "scheduler.lock"
_lock_handles: list = []  # keep file objects alive so the lock is held


def _acquire_scheduler_lock() -> bool:
    """Return True if this process may run the scheduled jobs.

    Uses an advisory file lock on Linux (the server). On Windows the module
    isn't available, but local development runs a single process anyway, so
    we simply allow it.
    """
    try:
        import fcntl
    except ImportError:
        return True

    try:
        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        handle = open(_LOCK_PATH, "w")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False

    handle.write(str(os.getpid()))
    handle.flush()
    _lock_handles.append(handle)
    return True


def _resolve_owner(lead: dict) -> dict | None:
    """Look up the owner config; log + return None if missing/unconfigured."""
    owner = get_user(lead["owner_id"])
    if owner is None:
        log.error(
            "Lead %s references unknown owner_id=%s — skipping",
            lead["id"],
            lead["owner_id"],
        )
        return None
    if not is_configured(owner):
        log.error(
            "Lead %s owner=%s has placeholder credentials — skipping",
            lead["id"],
            owner["id"],
        )
        return None
    return owner


def check_27h_reminders() -> None:
    """Send prospect reminders for booked meetings <=27h away. This mail
    goes straight to the prospect and needs no action from the owner."""
    now = datetime.now(timezone.utc)
    threshold = now + timedelta(hours=27)
    leads = get_pending_27h_reminders(now.isoformat(), threshold.isoformat())

    for lead in leads:
        owner = _resolve_owner(lead)
        if owner is None:
            continue
        try:
            brussels_dt = utc_to_brussels(lead["meeting_datetime"])
            datum = format_dutch(brussels_dt)
            html = render_template(
                "email_reminder.html",
                name=lead["name"],
                datum=datum,
                sender_name=owner["name"],
            )
            sender = sender_for(owner)
            send_email(
                lead["email"],
                f"Reminder: onze afspraak {datum}",
                html,
                from_address=sender["address"],
                from_password=sender["password"],
                from_name=sender["name"],
            )
            mark_27h_sent(lead["id"])
            log.info(
                "27h reminder sent for lead %s (%s) via %s",
                lead["id"],
                lead["email"],
                owner["id"],
            )
        except Exception:
            log.exception("Failed 27h reminder for lead %s", lead["id"])


def check_1h_notify_reminders() -> None:
    """Real-time safety net: ping the owner when a meeting is <=1h away.

    Disabled by default (OWNER_PINGS_ENABLED) while everyone shares one
    mailbox — otherwise all three sellers' pings land in the same inbox.
    """
    if not OWNER_PINGS_ENABLED:
        return

    now = datetime.now(timezone.utc)
    threshold = now + timedelta(hours=1)
    leads = get_pending_1h_notify_reminders(now.isoformat(), threshold.isoformat())

    for lead in leads:
        owner = _resolve_owner(lead)
        if owner is None:
            continue

        notify_email = notify_address_for(owner)

        try:
            brussels_dt = utc_to_brussels(lead["meeting_datetime"])
            body = f"""
            <html><body style="font-family: system-ui, Arial, sans-serif;">
                <h2>[Laatste-moment] Meeting over ~1 uur</h2>
                <p>Deze kwam te laat binnen voor de ochtend-digest.</p>
                <ul>
                    <li><strong>Naam:</strong> {lead['name']}</li>
                    <li><strong>Bedrijf:</strong> {lead['company']}</li>
                    <li><strong>Telefoon:</strong> {lead['phone'] or '-'}</li>
                    <li><strong>Tijd:</strong> {brussels_dt.strftime('%H:%M')}</li>
                </ul>
                <p><strong>Actie:</strong> stuur nu een WhatsApp-bericht:</p>
                <blockquote style="border-left: 3px solid #333; padding-left: 12px;">
                    Hey {lead['name']}, nog een uurtje tot ons gesprek om
                    {brussels_dt.strftime('%H:%M')} (...) tot zo!
                </blockquote>
            </body></html>
            """
            sender = sender_for(owner)
            send_email(
                notify_email,
                f"[SHOW-UP] Meeting over 1u - {lead['name']} van {lead['company']}",
                body,
                from_address=sender["address"],
                from_password=sender["password"],
                from_name=sender["name"],
            )
            mark_notify_sent(lead["id"])
            log.info(
                "1h fallback ping sent for lead %s to %s", lead["id"], notify_email
            )
        except Exception:
            log.exception("Failed 1h notify reminder for lead %s", lead["id"])


def _brussels_today_utc_window() -> tuple[str, str]:
    now_brussels = datetime.now(BRUSSELS_TZ)
    start_local = now_brussels.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )


_CARD = (
    "border-left: 3px solid {color}; background: {bg}; padding: 10px 14px; "
    "margin: 8px 0; border-radius: 4px;"
)


def _build_digest_html(
    owner: dict,
    meetings: list[dict],
    videos: list[dict],
    stale: list[dict],
    now_brussels: datetime,
) -> str:
    parts = [
        '<html><body style="font-family: system-ui, Arial, sans-serif; '
        'max-width: 640px; margin: 0 auto; color: #222; line-height: 1.6;">',
        f"<h2 style='margin-bottom:4px;'>Goeiemorgen {owner['name']}</h2>",
        f"<p style='color:#666;margin-top:0;'>{len(meetings)} meeting(s) vandaag "
        f"&middot; {len(videos)} filmpje(s) te sturen</p>",
    ]

    if meetings:
        parts.append("<h3>📅 WhatsApp-herinneringen (1u voor elke meeting)</h3>")
        for m in meetings:
            b = utc_to_brussels(m["meeting_datetime"])
            reminder_dt = b - timedelta(hours=1)
            if reminder_dt <= now_brussels:
                when = "<strong style='color:#c53030;'>NU METEEN</strong>"
            else:
                when = f"<strong>{reminder_dt.strftime('%H:%M')}</strong>"
            phone = (
                f" &middot; {m['phone']}"
                if m["phone"]
                else " &middot; <em>geen nummer — enkel mail mogelijk</em>"
            )
            parts.append(
                f"<div style=\"{_CARD.format(color='#1a73e8', bg='#f4f8ff')}\">"
                f"{when} &rarr; <strong>{m['name']}</strong> ({m['company']})"
                f"{phone}<br>"
                f"<span style='color:#666;font-size:13px;'>meeting om "
                f"{b.strftime('%H:%M')}</span><br>"
                f"<span style='display:inline-block;margin-top:6px;background:#fff;"
                f"border:1px solid #dde;padding:6px 10px;border-radius:4px;'>"
                f"Hey {m['name']}, nog een uurtje tot ons gesprek om "
                f"{b.strftime('%H:%M')} (...) tot zo!</span></div>"
            )

    if videos:
        parts.append("<h3>🎥 Intro-filmpjes nog te versturen</h3>")
        for v in videos:
            parts.append(
                f"<div style=\"{_CARD.format(color='#7c3aed', bg='#faf7ff')}\">"
                f"<strong>{v['name']}</strong> ({v['company']})"
                f"{' &middot; ' + v['phone'] if v['phone'] else ''}<br>"
                f"<span style='color:#666;font-size:13px;'>nummer is binnen — "
                f"stuur het korte kennismakingsfilmpje via WhatsApp</span></div>"
            )

    if stale:
        parts.append(f"<h3>⏳ Geen reactie ({STALE_DAYS}+ dagen)</h3>")
        for s in stale:
            parts.append(
                f"<div style=\"{_CARD.format(color='#d69e2e', bg='#fffaf0')}\">"
                f"<strong>{s['name']}</strong> ({s['company']})<br>"
                f"<span style='color:#666;font-size:13px;'>follow-upmail is "
                f"verstuurd, misschien tijd voor een belletje?</span></div>"
            )

    if not meetings and not videos and not stale:
        parts.append("<p>Niets openstaand voor vandaag. 🎉</p>")

    parts.append(
        "<p style='color:#999;font-size:12px;margin-top:28px;'>"
        "Oryn Show-Up System &middot; dagelijks overzicht</p></body></html>"
    )
    return "".join(parts)


def send_digest_for_owner(owner: dict, mark_notified: bool = True) -> bool:
    """Build + send one owner's digest. Returns True if a mail went out.

    When mark_notified is True (the real scheduled run) every meeting listed
    is flagged as notified, so the separate 1h ping does NOT also fire for it
    — that ping is only meant as a fallback for meetings booked after the
    digest already went out. The manual 'test' button passes False so testing
    never suppresses a real reminder.
    """
    if not is_configured(owner):
        return False

    day_start_iso, day_end_iso = _brussels_today_utc_window()
    stale_threshold = (
        datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)
    ).isoformat()

    meetings = [
        m
        for m in get_todays_booked_meetings(day_start_iso, day_end_iso)
        if m["owner_id"] == owner["id"]
    ]
    videos = [v for v in get_video_needed_leads() if v["owner_id"] == owner["id"]]
    stale = [
        s
        for s in get_stale_interested_leads(stale_threshold)
        if s["owner_id"] == owner["id"]
    ]

    if not meetings and not videos and not stale:
        return False  # nothing to report — no ruis in the inbox

    notify_email = notify_address_for(owner)
    html = _build_digest_html(
        owner, meetings, videos, stale, datetime.now(BRUSSELS_TZ)
    )

    sender = sender_for(owner)
    send_email(
        notify_email,
        f"[SHOW-UP] Vandaag: {len(meetings)} meeting(s), "
        f"{len(videos) + len(stale)} andere actie(s)",
        html,
        from_address=sender["address"],
        from_password=sender["password"],
        from_name=sender["name"],
    )
    log.info("Morning digest sent to %s", notify_email)

    if mark_notified:
        for m in meetings:
            mark_notify_sent(m["id"])

    return True


def send_morning_digest() -> None:
    """One consolidated email per owner listing every manual action for
    the day. Parked (DIGEST_ENABLED) until each seller has their own
    mailbox — see the module docstring."""
    if not DIGEST_ENABLED:
        return
    for owner in load_users():
        try:
            send_digest_for_owner(owner, mark_notified=True)
        except Exception:
            log.exception("Failed to send morning digest to owner %s", owner.get("id"))


def backup_database() -> None:
    """Nightly copy of the SQLite file, keeping the last BACKUP_KEEP_DAYS.

    Uses SQLite's own backup API rather than a plain file copy, so a backup
    taken while someone is saving a lead is still a consistent database.
    """
    import sqlite3

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(BRUSSELS_TZ).strftime("%Y-%m-%d")
        target = BACKUP_DIR / f"meetings-{stamp}.db"

        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(target)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        log.info("Database backup written to %s", target)

        cutoff = datetime.now(BRUSSELS_TZ) - timedelta(days=BACKUP_KEEP_DAYS)
        for old in BACKUP_DIR.glob("meetings-*.db"):
            try:
                day = datetime.strptime(old.stem.replace("meetings-", ""), "%Y-%m-%d")
                if day.replace(tzinfo=BRUSSELS_TZ) < cutoff:
                    old.unlink()
                    log.info("Removed old backup %s", old.name)
            except ValueError:
                continue
    except Exception:
        log.exception("Database backup failed")


def start_scheduler() -> BackgroundScheduler | None:
    """Start the background jobs — but only in the one process that wins
    the lock. Returns None in the processes that skip."""
    if not _acquire_scheduler_lock():
        log.info(
            "Another process already runs the scheduler — skipping in PID %s",
            os.getpid(),
        )
        return None

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        check_27h_reminders,
        "interval",
        seconds=60,
        id="27h_check",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        check_1h_notify_reminders,
        "interval",
        seconds=60,
        id="1h_notify_check",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        backup_database,
        "cron",
        hour=BACKUP_HOUR,
        minute=15,
        timezone=BRUSSELS_TZ,
        id="db_backup",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        send_morning_digest,
        "cron",
        hour=DIGEST_HOUR,
        minute=DIGEST_MINUTE,
        timezone=BRUSSELS_TZ,
        id="morning_digest",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    log.info(
        "Scheduler started in PID %s — 27h prospect reminders ON, "
        "owner pings %s, morning digest %s, nightly backup at %02d:15",
        os.getpid(),
        "ON" if OWNER_PINGS_ENABLED else "OFF (parked)",
        "ON" if DIGEST_ENABLED else "OFF (parked)",
        BACKUP_HOUR,
    )
    return scheduler
