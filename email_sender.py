"""SMTP email sending via Gmail with UTF-8 HTML templates + ICS invites.

Credentials are passed per-call so we can send from different Gmail
accounts (per user) within the same process.
"""

import logging
import smtplib
import uuid
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Optional

TEMPLATES_DIR = Path(__file__).parent / "templates"

log = logging.getLogger(__name__)


def render_template(template: str, **context) -> str:
    """Very small template renderer: replaces {{key}} with str(value)."""
    path = TEMPLATES_DIR / template
    content = path.read_text(encoding="utf-8")
    for key, value in context.items():
        content = content.replace("{{" + key + "}}", str(value))
    return content


def _escape_ics(text: str) -> str:
    """Escape special chars in ICS TEXT fields per RFC 5545."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(
    summary: str,
    description: str,
    start_utc: datetime,
    end_utc: datetime,
    organizer_email: str,
    organizer_name: str,
    attendee_email: str,
    attendee_name: str,
    uid: Optional[str] = None,
    meet_link: Optional[str] = None,
) -> str:
    """Build an RFC 5545 iCalendar VEVENT as a REQUEST (calendar invite).

    If meet_link is provided, it becomes the LOCATION and is added to the
    DESCRIPTION so Google Calendar auto-detects it as a Meet room.
    """
    if uid is None:
        uid = f"{uuid.uuid4()}@oryn.local"

    now = datetime.now(timezone.utc)

    if meet_link:
        location = meet_link
        full_description = f"{description}\n\nGoogle Meet: {meet_link}"
    else:
        location = "Telefonisch"
        full_description = description

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Oryn//ShowUp//NL",
        "METHOD:REQUEST",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_fmt_utc(now)}",
        f"DTSTART:{_fmt_utc(start_utc)}",
        f"DTEND:{_fmt_utc(end_utc)}",
        f"SUMMARY:{_escape_ics(summary)}",
        f"DESCRIPTION:{_escape_ics(full_description)}",
        f"LOCATION:{_escape_ics(location)}",
        f"ORGANIZER;CN={_escape_ics(organizer_name)}:MAILTO:{organizer_email}",
        f"ATTENDEE;CN={_escape_ics(attendee_name)};RSVP=TRUE;"
        f"PARTSTAT=NEEDS-ACTION:MAILTO:{attendee_email}",
    ]

    if meet_link:
        # RFC 7986 CONFERENCE property — modern clients render as video call
        lines.append(
            f"CONFERENCE;VALUE=URI;FEATURE=VIDEO;LABEL=Google Meet:{meet_link}"
        )
        lines.append(f"URL:{meet_link}")

    lines += [
        "STATUS:CONFIRMED",
        "SEQUENCE:0",
        "END:VEVENT",
        "END:VCALENDAR",
    ]

    # CRLF line endings per RFC 5545
    return "\r\n".join(lines)


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    from_address: str,
    from_password: str,
    from_name: str,
    ics_content: Optional[str] = None,
) -> None:
    """Send an email via Gmail SMTP using per-call credentials."""
    if not from_address or not from_password:
        raise RuntimeError(
            "from_address and from_password must be provided (per-user creds)"
        )

    # Structure: multipart/mixed → multipart/alternative(html + calendar) → ics attachment
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = formataddr((str(from_name), from_address))
    msg["To"] = to_email

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html", "utf-8"))

    if ics_content:
        # Inline calendar part — this is what triggers Gmail's native invite UI
        cal = MIMEText(ics_content, "calendar", "utf-8")
        cal.replace_header(
            "Content-Type",
            'text/calendar; charset="UTF-8"; method=REQUEST',
        )
        alt.attach(cal)

    msg.attach(alt)

    if ics_content:
        # Also attach as .ics file — some clients only handle attachments
        ics_attach = MIMEBase("application", "ics")
        ics_attach.set_payload(ics_content.encode("utf-8"))
        encoders.encode_base64(ics_attach)
        ics_attach.add_header(
            "Content-Disposition", 'attachment; filename="invite.ics"'
        )
        msg.attach(ics_attach)

    # Short-ish timeout: this call blocks the UI while you are on a call, so
    # failing fast beats a 30s freeze.
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
        server.starttls()
        server.login(from_address, from_password)
        server.send_message(msg)

    log.info(
        "Email sent from %s to %s: %s (calendar_invite=%s)",
        from_address,
        to_email,
        subject,
        bool(ics_content),
    )
