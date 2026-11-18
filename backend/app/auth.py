"""Dashboard password: log in, change it, and reset it with an emailed code.

- The first password comes from DASHBOARD_PASSWORD in .env.
- After someone changes or resets it, the new one is stored (hashed) in the database
  and DASHBOARD_PASSWORD no longer works.
- "Forgot password" emails a 6-digit code to RESET_EMAIL_TO (or ALERT_EMAIL_TO),
  using the same SMTP settings as the high-urgency alerts.
- Emergency reset (lost email too): on the server run
      docker exec reviewlens-db-1 psql -U reviewlens -c "DELETE FROM dashboard_auth;"
  and DASHBOARD_PASSWORD from .env works again.
"""
import hashlib
import hmac
import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import alerts
from .database import get_db
from .models import DashboardAuth

MIN_LENGTH = 8
MAX_FAILED_LOGINS = 10        # wrong passwords in a row ...
LOCK_MINUTES = 5              # ... lock logins for this long
CODE_MINUTES = 15             # a reset code works this long
CODE_MAX_TRIES = 5            # wrong codes before the code is cancelled
RESEND_SECONDS = 60           # at most one reset email per minute

router = APIRouter(prefix="/auth", tags=["dashboard password"])


# ---------- hashing (scrypt, from Python's standard library) ----------

def hash_secret(value: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(value.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_secret(value: str, stored: str | None) -> bool:
    try:
        scheme, salt, digest = (stored or "").split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    test = hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(test.hex(), digest)


# ---------- helpers ----------

def _row(db: Session) -> DashboardAuth:
    row = db.get(DashboardAuth, 1)
    if row is None:
        row = DashboardAuth(id=1)
        db.add(row)
    return row


def _password_matches(row: DashboardAuth, password: str) -> bool:
    if row.password_hash:
        return check_secret(password, row.password_hash)
    env_password = os.getenv("DASHBOARD_PASSWORD", "")
    if not env_password:
        raise HTTPException(503, "No dashboard password is set on the server (DASHBOARD_PASSWORD).")
    return hmac.compare_digest(password.encode(), env_password.encode())


def _check_password(db: Session, password: str) -> None:
    """Raises 401/429 for a wrong password (and counts it), otherwise clears the counter."""
    row = _row(db)
    now = datetime.now()
    if row.locked_until and row.locked_until > now:
        minutes = max(1, round((row.locked_until - now).total_seconds() / 60))
        raise HTTPException(429, f"Too many wrong passwords. Try again in {minutes} minute(s).")
    if not _password_matches(row, password):
        row.failed_logins = (row.failed_logins or 0) + 1
        if row.failed_logins >= MAX_FAILED_LOGINS:
            row.failed_logins, row.locked_until = 0, now + timedelta(minutes=LOCK_MINUTES)
        db.commit()
        raise HTTPException(401, "Wrong password.")
    row.failed_logins, row.locked_until = 0, None
    db.commit()


def _set_password(db: Session, new_password: str) -> None:
    row = _row(db)
    row.password_hash = hash_secret(new_password)
    row.changed_at = datetime.now()
    row.reset_code_hash = row.reset_expires_at = row.reset_attempts = None
    row.failed_logins, row.locked_until = 0, None
    db.commit()


def _reset_recipients() -> list[str]:
    return alerts.email_list("RESET_EMAIL_TO") or alerts.email_list("ALERT_EMAIL_TO")


def _mask(address: str) -> str:
    """owner@gmail.com -> o***@gmail.com (so the screen does not show the full address)."""
    name, _, domain = address.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


# ---------- request bodies ----------

NewPassword = Field(min_length=MIN_LENGTH, max_length=128)


class Login(BaseModel):
    password: str = Field(max_length=128)


class ChangePassword(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = NewPassword


class ResetPassword(BaseModel):
    code: str = Field(max_length=20)
    new_password: str = NewPassword


# ---------- endpoints ----------

@router.post("/login")
def login(body: Login, db: Session = Depends(get_db)):
    _check_password(db, body.password)
    return {"ok": True}


@router.post("/change-password")
def change_password(body: ChangePassword, db: Session = Depends(get_db)):
    _check_password(db, body.current_password)
    if body.new_password == body.current_password:
        raise HTTPException(400, "The new password must be different from the current one.")
    _set_password(db, body.new_password)
    return {"message": "Password changed. Use the new password next time you log in."}


@router.post("/forgot-password")
def forgot_password(db: Session = Depends(get_db)):
    """Email a 6-digit reset code to the admin address."""
    to = _reset_recipients()
    try:
        settings = alerts.alert_settings(to)
    except ValueError:
        settings = None
    if settings is None:
        raise HTTPException(503, "Password reset by email is not set up on the server "
                                 "(needs SMTP_HOST and RESET_EMAIL_TO or ALERT_EMAIL_TO). Ask the admin.")
    row = _row(db)
    now = datetime.now()
    if row.reset_sent_at and (now - row.reset_sent_at).total_seconds() < RESEND_SECONDS:
        raise HTTPException(429, "A code was just sent. Wait a minute before asking for another one.")

    code = f"{secrets.randbelow(10**6):06d}"
    msg = EmailMessage()
    msg["Subject"] = "ReviewLens: your password reset code"
    msg["From"] = settings["sender"]
    msg["To"] = ", ".join(to)
    lines = [f"Your ReviewLens reset code is: {code}", "",
             f"It works for {CODE_MINUTES} minutes. Type it on the login page under 'Forgot password?'.",
             "If you did not ask for this, ignore this email: your password stays the same."]
    if settings["dashboard_url"]:
        lines += ["", settings["dashboard_url"]]
    msg.set_content("\n".join(lines + ["— ReviewLens"]))
    try:
        alerts.send(msg, settings)
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        raise HTTPException(502, f"Could not send the email ({type(exc).__name__}). Check the SMTP settings.")

    row.reset_code_hash = hash_secret(code)
    row.reset_sent_at = now
    row.reset_expires_at = now + timedelta(minutes=CODE_MINUTES)
    row.reset_attempts = 0
    db.commit()
    return {"message": f"A 6-digit code was sent to {', '.join(_mask(a) for a in to)}. "
                       f"It works for {CODE_MINUTES} minutes."}


@router.post("/reset-password")
def reset_password(body: ResetPassword, db: Session = Depends(get_db)):
    row = _row(db)
    if not row.reset_code_hash or not row.reset_expires_at or row.reset_expires_at < datetime.now():
        raise HTTPException(400, "No valid code. Ask for a new one.")
    if not check_secret(body.code.strip(), row.reset_code_hash):
        row.reset_attempts = (row.reset_attempts or 0) + 1
        if row.reset_attempts >= CODE_MAX_TRIES:
            row.reset_code_hash = row.reset_expires_at = None
            db.commit()
            raise HTTPException(400, "Too many wrong codes. Ask for a new one.")
        db.commit()
        raise HTTPException(400, "Wrong code.")
    _set_password(db, body.new_password)
    return {"message": "Password reset. You can log in with the new password now."}
