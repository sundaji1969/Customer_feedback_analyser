"""Optional email alert when an upload contains new HIGH-urgency reviews.

Off unless ALERT_EMAIL_TO and SMTP_HOST are set. One email per upload lists every new
HIGH review, so food-safety, fraud and legal complaints are not missed.
A mail problem never fails the upload: it is reported back as a message instead.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage

MAX_TEXT = 600  # characters of each review shown in the email


def email_list(name: str) -> list[str]:
    """Comma-separated addresses from an environment variable."""
    return [a.strip() for a in os.getenv(name, "").split(",") if a.strip()]


def alert_settings(to: list[str] | None = None) -> dict | None:
    """Mail settings from the environment, or None when email is switched off.
    `to` defaults to ALERT_EMAIL_TO (password-reset emails pass their own list)."""
    to = email_list("ALERT_EMAIL_TO") if to is None else to
    host = os.getenv("SMTP_HOST", "").strip()
    if not to or not host:
        return None
    user = os.getenv("SMTP_USER", "").strip()
    return {
        "to": to,
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "").strip() or 587),
        "user": user,
        "password": os.getenv("SMTP_PASSWORD", ""),
        "sender": os.getenv("ALERT_EMAIL_FROM", "").strip() or user,
        "dashboard_url": os.getenv("DASHBOARD_URL", "").strip(),
    }


def _short(value, limit=MAX_TEXT) -> str:
    text = "" if value is None else str(value).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_message(reviews: list[dict], settings: dict) -> EmailMessage:
    n = len(reviews)
    msg = EmailMessage()
    msg["Subject"] = f"ReviewLens: {n} HIGH-urgency review{'s' if n != 1 else ''} need attention"
    msg["From"] = settings["sender"]
    msg["To"] = ", ".join(settings["to"])

    lines = [f"{n} new review{'s' if n != 1 else ''} were tagged HIGH urgency "
             "(health/safety, fraud, money taken, legal threat or abusive staff).", ""]
    for i, r in enumerate(reviews, 1):
        stars = f"{r['rating']}★" if r.get("rating") is not None else "no rating"
        when = r["date"].strftime("%d %b %Y") if r.get("date") else "no date"
        lines += [
            f"{i}. {r['review_id']} · {r.get('platform') or 'unknown platform'} · {stars} · {when} · {r.get('category')}",
            f"   Summary: {_short(r.get('summary'), 300)}",
            f"   Customer wrote: {_short(r.get('review_text'))}",
            f"   Suggested reply: {_short(r.get('suggested_reply'))}",
            "",
        ]
    if settings["dashboard_url"]:
        lines.append(f"Open the Action queue: {settings['dashboard_url']}")
    lines.append("— ReviewLens")
    msg.set_content("\n".join(lines))  # UTF-8, so Tamil text arrives intact
    return msg


def send(msg: EmailMessage, s: dict) -> None:
    context = ssl.create_default_context()
    if s["port"] == 465:
        server = smtplib.SMTP_SSL(s["host"], s["port"], timeout=20, context=context)
    else:
        server = smtplib.SMTP(s["host"], s["port"], timeout=20)
    with server:
        if s["port"] != 465:
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls(context=context)
                server.ehlo()
        if s["user"]:
            server.login(s["user"], s["password"])
        server.send_message(msg)


def send_high_urgency_alert(reviews: list[dict]) -> str | None:
    """Email the given HIGH reviews. Returns a short status message, or None if nothing was due."""
    if not reviews:
        return None
    try:
        settings = alert_settings()
    except ValueError:
        return "Alert email FAILED (SMTP_PORT must be a number, e.g. 587)"
    if settings is None:
        return None
    try:
        send(build_message(reviews, settings), settings)
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        return f"Alert email FAILED ({type(exc).__name__}: {exc})"[:300]
    n = len(reviews)
    return f"Alert email sent to {', '.join(settings['to'])} for {n} high-urgency review{'s' if n != 1 else ''}."
