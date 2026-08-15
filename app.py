"""Flask web UI for adding leads, booking meetings, tracking follow-up
state, and per-user login."""

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlencode

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from db import (
    add_lead,
    book_meeting,
    cancel_lead,
    delete_lead,
    find_open_lead_by_email,
    get_lead,
    list_leads,
    mark_27h_sent,
    mark_confirm_sent,
    mark_followup_sent,
    mark_notify_sent,
    mark_outcome,
    mark_video_sent,
    restore_lead,
    update_contact,
)
from email_sender import build_ics
from email_sender import render_template as render_email_template
from email_sender import send_email
from users import (
    get_user,
    is_configured,
    load_users,
    notify_address_for,
    sender_for,
)
from utils import BRUSSELS_TZ, brussels_to_utc, format_dutch, utc_to_brussels

# Meeting duration used in the calendar invite
MEETING_DURATION_MINUTES = 30

load_dotenv()

log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret-change-me")
app.permanent_session_lifetime = timedelta(days=30)

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Skip 27h reminder if meeting is booked within this window
_27H_SECONDS = 27 * 3600
# Skip 1h notify ping if meeting is booked within this window
_1H_SECONDS = 60 * 60

# Templates keyed by (booked: bool, contact_type: 'personal'|'reception')
_CONFIRM_TEMPLATES = {
    "personal": "email_confirm_personal.html",
    "reception": "email_confirm_reception.html",
}
_FOLLOWUP_TEMPLATES = {
    "personal": "email_followup_personal.html",
    "reception": "email_followup_reception.html",
}


def _contact_type_or_default(value: str) -> str:
    return value if value in ("personal", "reception") else "reception"


def _template_key(lead: dict) -> str:
    """Which mail variant to send.

    'personal' = we already have a direct number, so no need to ask for one.
    'reception' = we only have the reception number OR no number at all —
    either way the mail should ask for a direct number. Falling back on
    'reception' when the phone field is empty matters: otherwise a lead added
    without any number would get the mail that assumes we can already reach
    them on WhatsApp.
    """
    if lead.get("phone") and lead.get("contact_type") == "personal":
        return "personal"
    return "reception"


def build_gcal_url(
    name: str,
    company: str,
    email: str,
    start_utc: datetime,
    end_utc: datetime,
    owner: dict,
) -> str:
    """Build a Google Calendar 'create event' template URL — opens prefilled
    with the prospect already added as a guest.

    This button is now the ONE place the calendar invite comes from. The
    confirmation mail no longer attaches an ICS file, so there is no double
    invite. Sending it manually from Google Calendar means the event lives
    in the owner's real calendar, which is what lets him attach a unique
    Google Meet link to it before (or after) inviting the prospect.
    """
    fmt = "%Y%m%dT%H%M%SZ"
    params = {
        "action": "TEMPLATE",
        "text": f"Afspraak {name} ({company}) - Oryn",
        "dates": f"{start_utc.strftime(fmt)}/{end_utc.strftime(fmt)}",
        "details": (
            f"Afspraak tussen {owner['name']} (Oryn) en {name} van {company}."
        ),
        "add": email,
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params)


def _send_booking_confirmation(lead: dict, owner: dict, meeting_utc_iso: str) -> None:
    """Send the confirmation mail (1 or 2, depending on contact_type) and
    mark reminder flags for short-notice bookings.

    No ICS attachment: the calendar invite is sent manually from Google
    Calendar via the agenda button in the dashboard. That way the event
    lives in the owner's real calendar and can carry a unique Google Meet
    link — and the prospect only ever receives ONE invite.
    """
    lead_id = lead["id"]
    meeting_utc_dt = datetime.fromisoformat(meeting_utc_iso)
    now_utc = datetime.now(timezone.utc)
    seconds_until = (meeting_utc_dt - now_utc).total_seconds()

    if seconds_until < _27H_SECONDS:
        mark_27h_sent(lead_id)
    if seconds_until < _1H_SECONDS:
        mark_notify_sent(lead_id)

    brussels_dt = utc_to_brussels(meeting_utc_iso)
    datum = format_dutch(brussels_dt)

    template = _CONFIRM_TEMPLATES[_template_key(lead)]

    html = render_email_template(
        template,
        name=lead["name"],
        company=lead["company"],
        niche=lead["niche"] or "uw sector",
        datum=datum,
        sender_name=owner["name"],
    )

    sender = sender_for(owner)
    send_email(
        lead["email"],
        f"Bevestiging AI-consultatie — {datum}",
        html,
        from_address=sender["address"],
        from_password=sender["password"],
        from_name=sender["name"],
    )
    mark_confirm_sent(lead_id)


def _send_followup(lead: dict, owner: dict) -> None:
    """Send the not-yet-convinced follow-up mail (3 or 4, depending on
    contact_type) — no calendar invite, no meeting time yet."""
    template = _FOLLOWUP_TEMPLATES[_template_key(lead)]

    html = render_email_template(
        template,
        name=lead["name"],
        company=lead["company"],
        niche=lead["niche"] or "uw sector",
        sender_name=owner["name"],
    )

    sender = sender_for(owner)
    send_email(
        lead["email"],
        f"Even kort — AI-consultatie voor {lead['company']}",
        html,
        from_address=sender["address"],
        from_password=sender["password"],
        from_name=sender["name"],
    )
    mark_followup_sent(lead["id"])


# --- Auth helpers ---------------------------------------------------------


def current_user() -> dict | None:
    uid = session.get("user_id")
    if not uid:
        return None
    return get_user(uid)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


# --- Routes ---------------------------------------------------------------


@app.route("/login", methods=["GET", "POST"])
def login():
    users = load_users()
    if request.method == "POST":
        uid = request.form.get("user_id", "").strip()
        user = get_user(uid)
        if user is None:
            flash("Onbekende gebruiker.", "error")
            return redirect(url_for("login"))
        session.permanent = True
        session["user_id"] = user["id"]
        flash(f"Ingelogd als {user['name']}.", "success")
        return redirect(url_for("index"))
    return render_template("login.html", users=users)


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/", methods=["GET"])
@login_required
def index():
    leads = list_leads()
    now_brussels = datetime.now(BRUSSELS_TZ)
    today = now_brussels.date()
    tomorrow = today + timedelta(days=1)

    users_by_id = {u["id"]: u for u in load_users()}
    for lead in leads:
        owner = users_by_id.get(lead["owner_id"])
        lead["owner_color"] = owner["color"] if owner else "#666"
        lead["is_today"] = False
        lead["when_label"] = None

        if lead["meeting_datetime"]:
            b = utc_to_brussels(lead["meeting_datetime"])
            lead["display_datetime"] = b.strftime("%H:%M %d/%m/%Y")
            lead["is_past"] = b < now_brussels
            lead["_ts"] = b.timestamp()
            if b.date() == today:
                lead["is_today"] = True
                lead["when_label"] = f"VANDAAG {b.strftime('%H:%M')}"
            elif b.date() == tomorrow:
                lead["when_label"] = f"morgen {b.strftime('%H:%M')}"
        else:
            lead["display_datetime"] = None
            lead["is_past"] = False
            lead["_ts"] = datetime.fromisoformat(lead["created_at"]).timestamp()

        lead["_inactive"] = bool(lead["cancelled"]) or lead["is_past"]

        # Does this row need me to physically do something?
        lead["needs_action"] = bool(
            (lead["phone"] and lead["video_needed"] and not lead["video_sent"])
            or (lead["status"] == "booked" and lead["is_past"] and not lead["outcome"])
        ) and not lead["cancelled"]

        # Filter bucket used by the tabs in the UI
        if lead["cancelled"]:
            lead["bucket"] = "afgesloten"
        elif lead["status"] == "interested":
            lead["bucket"] = "interested"
        elif lead["is_past"]:
            lead["bucket"] = "afgesloten"
        else:
            lead["bucket"] = "meeting"

        # Prefilled Google Calendar link — only for active upcoming meetings
        lead["gcal_url"] = None
        if (
            lead["status"] == "booked"
            and not lead["_inactive"]
            and owner is not None
        ):
            start_utc = datetime.fromisoformat(lead["meeting_datetime"])
            if start_utc.tzinfo is None:
                start_utc = start_utc.replace(tzinfo=timezone.utc)
            end_utc = start_utc + timedelta(minutes=MEETING_DURATION_MINUTES)
            lead["gcal_url"] = build_gcal_url(
                lead["name"], lead["company"], lead["email"], start_utc, end_utc, owner
            )

    def sort_key(m: dict):
        # 0 = upcoming meetings (soonest first — what you act on today)
        # 1 = not-yet-convinced leads (newest first — freshest follow-ups)
        # 2 = past/cancelled (most recent first)
        if m["bucket"] == "meeting":
            return (0, m["_ts"])
        if m["bucket"] == "interested":
            return (1, -m["_ts"])
        return (2, -m["_ts"])

    leads.sort(key=sort_key)

    stats = {
        "today": sum(1 for m in leads if m["is_today"] and m["bucket"] == "meeting"),
        "upcoming": sum(1 for m in leads if m["bucket"] == "meeting"),
        "interested": sum(1 for m in leads if m["bucket"] == "interested"),
        "actions": sum(1 for m in leads if m["needs_action"]),
    }

    return render_template("index.html", leads=leads, stats=stats)


@app.route("/add", methods=["POST"])
@login_required
def add():
    user = current_user()
    if not is_configured(user):
        flash(
            "Er is nog geen mailbox ingesteld om vanuit te versturen. "
            "Vul SMTP_ADDRESS en SMTP_PASSWORD in het .env-bestand in "
            "(of zet persoonlijke gegevens bij deze gebruiker in users.json).",
            "error",
        )
        return redirect(url_for("index"))

    name = request.form.get("name", "").strip()
    company = request.form.get("company", "").strip()
    email = request.form.get("email", "").strip().lower()
    niche = request.form.get("niche", "").strip()
    phone = request.form.get("phone", "").strip()
    contact_type = _contact_type_or_default(request.form.get("contact_type", ""))
    whatsapp_consent = request.form.get("whatsapp_consent") == "on"
    booking_mode = request.form.get("booking_mode", "interested")

    if not name or not company or not email:
        flash("Naam, bedrijf en email zijn verplicht.", "error")
        return redirect(url_for("index"))

    if not EMAIL_REGEX.match(email):
        flash("Ongeldig emailadres.", "error")
        return redirect(url_for("index"))

    existing = find_open_lead_by_email(email)
    if existing:
        if existing["status"] == "interested":
            flash(
                f"{existing['name']} ({existing['company']}) staat al in de lijst "
                f"als 'niet overtuigd' — die kreeg de follow-upmail al. Gebruik "
                f"'boek nu' op die rij in plaats van opnieuw toe te voegen.",
                "error",
            )
        else:
            flash(
                f"Er staat al een actieve meeting voor {email}. "
                f"Annuleer die eerst of gebruik een ander adres.",
                "error",
            )
        return redirect(url_for("index"))

    meeting_utc_iso = None
    if booking_mode == "book":
        meeting_date = request.form.get("meeting_date", "").strip()
        meeting_time = request.form.get("meeting_time", "").strip()
        if not meeting_date or not meeting_time:
            flash("Datum en tijd zijn verplicht om een meeting te boeken.", "error")
            return redirect(url_for("index"))

        try:
            meeting_utc_iso = brussels_to_utc(f"{meeting_date}T{meeting_time}")
        except ValueError:
            flash("Ongeldige datum/tijd.", "error")
            return redirect(url_for("index"))

        meeting_utc_dt = datetime.fromisoformat(meeting_utc_iso)
        if (meeting_utc_dt - datetime.now(timezone.utc)).total_seconds() <= 0:
            flash("Meeting moet in de toekomst zijn.", "error")
            return redirect(url_for("index"))

    lead_id = add_lead(
        owner_id=user["id"],
        owner_name=user["name"],
        name=name,
        company=company,
        email=email,
        contact_type=contact_type,
        phone=phone or None,
        niche=niche or None,
        whatsapp_consent=whatsapp_consent,
        meeting_datetime_utc_iso=meeting_utc_iso,
    )
    lead = get_lead(lead_id)

    try:
        if meeting_utc_iso:
            _send_booking_confirmation(lead, user, meeting_utc_iso)
            flash(
                f"Lead toegevoegd + meeting geboekt. Bevestigingsmail + calendar "
                f"invite verstuurd naar {email}.",
                "success",
            )
        else:
            _send_followup(lead, user)
            flash(
                f"Lead toegevoegd als 'nog niet overtuigd'. Follow-upmail "
                f"verstuurd naar {email}. Zodra ze reageren: klik 'boek nu' "
                f"in de tabel.",
                "success",
            )
    except Exception as exc:
        log.exception("Failed to send mail for lead %s", lead_id)
        flash(
            f"Lead is opgeslagen MAAR de mail faalde: {exc}. "
            f"Controleer je Gmail credentials en internetverbinding.",
            "error",
        )

    return redirect(url_for("index"))


@app.route("/book/<int:lead_id>", methods=["POST"])
@login_required
def book(lead_id: int):
    """Convert a not-yet-convinced lead into a booked meeting."""
    user = current_user()
    lead = get_lead(lead_id)
    if lead is None:
        flash("Lead niet gevonden.", "error")
        return redirect(url_for("index"))

    meeting_date = request.form.get("meeting_date", "").strip()
    meeting_time = request.form.get("meeting_time", "").strip()
    if not meeting_date or not meeting_time:
        flash("Datum en tijd zijn verplicht.", "error")
        return redirect(url_for("index"))

    try:
        meeting_utc_iso = brussels_to_utc(f"{meeting_date}T{meeting_time}")
    except ValueError:
        flash("Ongeldige datum/tijd.", "error")
        return redirect(url_for("index"))

    meeting_utc_dt = datetime.fromisoformat(meeting_utc_iso)
    if (meeting_utc_dt - datetime.now(timezone.utc)).total_seconds() <= 0:
        flash("Meeting moet in de toekomst zijn.", "error")
        return redirect(url_for("index"))

    owner = get_user(lead["owner_id"]) or user
    book_meeting(lead_id, meeting_utc_iso)
    lead = get_lead(lead_id)

    try:
        _send_booking_confirmation(lead, owner, meeting_utc_iso)
        flash(
            f"Meeting geboekt voor {lead['name']}. Bevestigingsmail verstuurd.",
            "success",
        )
    except Exception as exc:
        log.exception("Failed to send booking confirmation for lead %s", lead_id)
        flash(f"Meeting geboekt MAAR bevestigingsmail faalde: {exc}", "error")

    return redirect(url_for("index"))


@app.route("/contact/<int:lead_id>", methods=["POST"])
@login_required
def contact(lead_id: int):
    """Add/update a lead's phone number — flags the WhatsApp intro video
    as something to send (shows up in the morning digest)."""
    lead = get_lead(lead_id)
    if lead is None:
        flash("Lead niet gevonden.", "error")
        return redirect(url_for("index"))

    phone = request.form.get("phone", "").strip()
    contact_type = _contact_type_or_default(request.form.get("contact_type", "personal"))
    whatsapp_consent = request.form.get("whatsapp_consent") == "on"

    if not phone:
        flash("Vul een telefoonnummer in.", "error")
        return redirect(url_for("index"))

    update_contact(lead_id, phone, contact_type, whatsapp_consent)
    flash(
        f"Nummer toegevoegd voor {lead['name']}. Filmpje staat morgen in je "
        f"ochtend-digest.",
        "success",
    )
    return redirect(url_for("index"))


@app.route("/video_sent/<int:lead_id>", methods=["POST"])
@login_required
def video_sent(lead_id: int):
    mark_video_sent(lead_id)
    flash("Gemarkeerd als verstuurd.", "success")
    return redirect(url_for("index"))


@app.route("/outcome/<int:lead_id>/<outcome>", methods=["POST"])
@login_required
def outcome(lead_id: int, outcome: str):
    if outcome not in ("fit", "no_fit"):
        flash("Ongeldige outcome.", "error")
        return redirect(url_for("index"))
    mark_outcome(lead_id, outcome)
    flash("Resultaat opgeslagen.", "success")
    return redirect(url_for("index"))


@app.route("/digest_test", methods=["POST"])
@login_required
def digest_test():
    """Send the morning digest right now, to yourself — so you can see what
    it looks like without waiting until tomorrow morning. Does not mark
    anything as notified, so it can't suppress a real reminder."""
    from scheduler import send_digest_for_owner

    user = current_user()
    try:
        sent = send_digest_for_owner(user, mark_notified=False)
        if sent:
            flash(
                f"Test-overzicht verstuurd naar {notify_address_for(user)}.",
                "success",
            )
        else:
            flash(
                "Niets te melden op dit moment — geen meeting vandaag, geen "
                "filmpje te sturen. Voeg eerst een lead toe om het te testen.",
                "error",
            )
    except Exception as exc:
        log.exception("Digest test failed")
        flash(f"Versturen mislukt: {exc}", "error")
    return redirect(url_for("index"))


@app.route("/uncancel/<int:lead_id>", methods=["POST"])
@login_required
def uncancel(lead_id: int):
    """Undo an accidental cancel."""
    restore_lead(lead_id)
    flash("Terug actief gezet.", "success")
    return redirect(url_for("index"))


@app.route("/cancel/<int:lead_id>", methods=["POST"])
@login_required
def cancel(lead_id: int):
    cancel_lead(lead_id)
    flash("Geannuleerd. Er worden geen reminders meer verstuurd.", "success")
    return redirect(url_for("index"))


@app.route("/delete/<int:lead_id>", methods=["POST"])
@login_required
def delete(lead_id: int):
    delete_lead(lead_id)
    flash("Verwijderd.", "success")
    return redirect(url_for("index"))
