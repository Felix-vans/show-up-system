"""SQLite database for storing leads (booked meetings + not-yet-convinced
follow-up contacts) and their reminder/follow-up state.

Table is called `leads` because not every row has a meeting yet — a lead
starts as `status='interested'` (cold call happened, prospect wasn't ready
to book) and can later become `status='booked'` once a meeting time is set.
"""

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from utils import now_utc_iso

DB_PATH = Path(__file__).parent / "data" / "meetings.db"

log = logging.getLogger(__name__)

# Additive columns — safe to add to an existing `leads` table on every boot.
# (column_name -> SQL type/default clause)
_ADDITIVE_COLUMNS = {
    "phone": "TEXT",
    "niche": "TEXT",
    "whatsapp_consent": "INTEGER DEFAULT 0",
    "followup_sent": "INTEGER DEFAULT 0",
    "video_sent": "INTEGER DEFAULT 0",
    "video_needed": "INTEGER DEFAULT 0",
    "outcome": "TEXT",
    "updated_at": "TEXT",
}


def init_db() -> None:
    DB_PATH.parent.mkdir(exist_ok=True)
    with get_conn() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "leads" not in tables:
            conn.execute(
                """
                CREATE TABLE leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL,
                    owner_name TEXT NOT NULL,
                    name TEXT NOT NULL,
                    company TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT,
                    contact_type TEXT NOT NULL DEFAULT 'onbekend',
                    niche TEXT,
                    whatsapp_consent INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'interested',
                    meeting_datetime TEXT,
                    confirm_sent INTEGER DEFAULT 0,
                    followup_sent INTEGER DEFAULT 0,
                    reminder_27h_sent INTEGER DEFAULT 0,
                    reminder_notify_sent INTEGER DEFAULT 0,
                    video_sent INTEGER DEFAULT 0,
                    video_needed INTEGER DEFAULT 0,
                    outcome TEXT,
                    cancelled INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                )
                """
            )
            log.info("Created new 'leads' table")

            # One-time migration from the old single-purpose 'meetings' table
            # (pre-existing booked-meeting-only schema). Preserves real data.
            if "meetings" in tables:
                old_cols = {
                    r[1]
                    for r in conn.execute(
                        "PRAGMA table_info(meetings)"
                    ).fetchall()
                }
                if "owner_id" in old_cols:
                    rows = conn.execute("SELECT * FROM meetings").fetchall()
                    for r in rows:
                        d = dict(r)
                        conn.execute(
                            """
                            INSERT INTO leads
                                (owner_id, owner_name, name, company, email,
                                 contact_type, status, meeting_datetime,
                                 confirm_sent, reminder_27h_sent,
                                 reminder_notify_sent, cancelled, created_at)
                            VALUES (?, ?, ?, ?, ?, 'onbekend', 'booked',
                                    ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                d["owner_id"],
                                d["owner_name"],
                                d["name"],
                                d["company"],
                                d["email"],
                                d["meeting_datetime"],
                                d["confirm_sent"],
                                d["reminder_27h_sent"],
                                d["reminder_notify_sent"],
                                d["cancelled"],
                                d["created_at"],
                            ),
                        )
                    conn.execute("DROP TABLE meetings")
                    log.warning(
                        "Migrated %d row(s) from old 'meetings' table into "
                        "'leads' (status=booked)",
                        len(rows),
                    )
        else:
            # Additive migration: add any new columns that don't exist yet.
            cols = {
                r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()
            }
            for col, decl in _ADDITIVE_COLUMNS.items():
                if col not in cols:
                    conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {decl}")
                    log.info("Added missing column leads.%s", col)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- Create ----------------------------------------------------------------


def add_lead(
    owner_id: str,
    owner_name: str,
    name: str,
    company: str,
    email: str,
    contact_type: str,
    phone: Optional[str] = None,
    niche: Optional[str] = None,
    whatsapp_consent: bool = False,
    meeting_datetime_utc_iso: Optional[str] = None,
) -> int:
    """Insert a new lead. status is 'booked' if a meeting time is given,
    otherwise 'interested' (not-yet-convinced follow-up track)."""
    status = "booked" if meeting_datetime_utc_iso else "interested"
    now = now_utc_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO leads
                (owner_id, owner_name, name, company, email, phone,
                 contact_type, niche, whatsapp_consent, status,
                 meeting_datetime, video_needed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_id,
                owner_name,
                name,
                company,
                email,
                phone,
                contact_type,
                niche,
                int(whatsapp_consent),
                status,
                meeting_datetime_utc_iso,
                1 if phone else 0,
                now,
                now,
            ),
        )
        return cur.lastrowid


# --- Read --------------------------------------------------------------


def get_lead(lead_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()
        return dict(row) if row else None


def list_leads() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM leads
            ORDER BY COALESCE(meeting_datetime, created_at) DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def has_active_meeting_for_email(email: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id FROM leads
            WHERE email = ?
              AND status = 'booked'
              AND cancelled = 0
              AND meeting_datetime > ?
            """,
            (email, now_utc_iso()),
        ).fetchone()
        return row is not None


def find_open_lead_by_email(email: str) -> Optional[dict]:
    """Any non-cancelled lead for this email that is still 'open': either an
    upcoming booked meeting, or a not-yet-convinced lead. Used to stop you
    from accidentally creating a second row for someone already in the list
    (which would re-send a follow-up mail they already got)."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM leads
            WHERE email = ?
              AND cancelled = 0
              AND (status = 'interested'
                   OR (status = 'booked' AND meeting_datetime > ?))
            ORDER BY id DESC
            """,
            (email, now_utc_iso()),
        ).fetchone()
        return dict(row) if row else None


# --- Update: status transitions -----------------------------------------


def book_meeting(lead_id: int, meeting_datetime_utc_iso: str) -> None:
    """Convert an 'interested' (not-yet-convinced) lead into a booked
    meeting. Resets reminder flags so the new meeting gets its own
    confirmation + 27h reminder cycle."""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE leads
            SET status = 'booked',
                meeting_datetime = ?,
                confirm_sent = 0,
                reminder_27h_sent = 0,
                reminder_notify_sent = 0,
                outcome = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (meeting_datetime_utc_iso, now_utc_iso(), lead_id),
        )


def update_contact(
    lead_id: int,
    phone: str,
    contact_type: str = "personal",
    whatsapp_consent: bool = True,
) -> None:
    """Add/update a lead's phone number (e.g. once the personal number
    comes in after only having the reception number). Flags that the
    WhatsApp intro video still needs to go out."""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE leads
            SET phone = ?, contact_type = ?, whatsapp_consent = ?,
                video_needed = 1, video_sent = 0, updated_at = ?
            WHERE id = ?
            """,
            (phone, contact_type, int(whatsapp_consent), now_utc_iso(), lead_id),
        )


def mark_outcome(lead_id: int, outcome: str) -> None:
    """outcome: 'fit' or 'no_fit' — set after a meeting has taken place."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET outcome = ?, updated_at = ? WHERE id = ?",
            (outcome, now_utc_iso(), lead_id),
        )


def cancel_lead(lead_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET cancelled = 1, updated_at = ? WHERE id = ?",
            (now_utc_iso(), lead_id),
        )


def restore_lead(lead_id: int) -> None:
    """Undo a cancel (mis-click recovery)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET cancelled = 0, updated_at = ? WHERE id = ?",
            (now_utc_iso(), lead_id),
        )


def delete_lead(lead_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))


# --- Update: reminder/email flags ----------------------------------------


def mark_confirm_sent(lead_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET confirm_sent = 1 WHERE id = ?", (lead_id,)
        )


def mark_followup_sent(lead_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET followup_sent = 1 WHERE id = ?", (lead_id,)
        )


def mark_27h_sent(lead_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET reminder_27h_sent = 1 WHERE id = ?", (lead_id,)
        )


def mark_notify_sent(lead_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET reminder_notify_sent = 1 WHERE id = ?",
            (lead_id,),
        )


def mark_video_sent(lead_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET video_sent = 1, video_needed = 0 WHERE id = ?",
            (lead_id,),
        )


# --- Read: scheduler / digest queries -------------------------------------


def get_pending_27h_reminders(now_iso: str, threshold_iso: str) -> list[dict]:
    """Booked meetings still in the future, within the 27h window, not yet
    reminded."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM leads
            WHERE status = 'booked'
              AND reminder_27h_sent = 0
              AND cancelled = 0
              AND meeting_datetime > ?
              AND meeting_datetime <= ?
            """,
            (now_iso, threshold_iso),
        ).fetchall()
        return [dict(r) for r in rows]


def get_pending_1h_notify_reminders(
    now_iso: str, threshold_iso: str
) -> list[dict]:
    """Booked meetings <=1h away, no owner-notification ping sent yet.
    Real-time safety net for meetings booked too late to appear in the
    morning digest."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM leads
            WHERE status = 'booked'
              AND reminder_notify_sent = 0
              AND cancelled = 0
              AND meeting_datetime > ?
              AND meeting_datetime <= ?
            """,
            (now_iso, threshold_iso),
        ).fetchall()
        return [dict(r) for r in rows]


def get_todays_booked_meetings(day_start_utc_iso: str, day_end_utc_iso: str) -> list[dict]:
    """Booked, active meetings happening within a UTC day window — used to
    build the morning digest."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM leads
            WHERE status = 'booked'
              AND cancelled = 0
              AND meeting_datetime >= ?
              AND meeting_datetime < ?
            ORDER BY meeting_datetime ASC
            """,
            (day_start_utc_iso, day_end_utc_iso),
        ).fetchall()
        return [dict(r) for r in rows]


def get_video_needed_leads() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM leads
            WHERE video_needed = 1 AND video_sent = 0 AND cancelled = 0
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_stale_interested_leads(older_than_iso: str) -> list[dict]:
    """'interested' leads (not-yet-convinced, no meeting) that have had no
    update in a while — gentle nudge in the digest to follow up manually."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM leads
            WHERE status = 'interested'
              AND cancelled = 0
              AND COALESCE(updated_at, created_at) <= ?
            ORDER BY created_at ASC
            """,
            (older_than_iso,),
        ).fetchall()
        return [dict(r) for r in rows]
