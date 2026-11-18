"""Database tables."""
import datetime as dt

from sqlalchemy import Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # --- Columns from the uploaded CSV ---
    review_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    platform: Mapped[str | None] = mapped_column(String(100))
    rating: Mapped[int | None] = mapped_column(Integer)
    review_text: Mapped[str] = mapped_column(Text)

    # --- Filled in by the AI ---
    sentiment: Mapped[str | None] = mapped_column(String(20), index=True)   # positive/neutral/negative
    category: Mapped[str | None] = mapped_column(String(50), index=True)
    urgency: Mapped[str | None] = mapped_column(String(10), index=True)     # HIGH/MEDIUM/LOW
    language: Mapped[str | None] = mapped_column(String(20))                # English/Tamil/Tanglish
    summary: Mapped[str | None] = mapped_column(Text)
    suggested_reply: Mapped[str | None] = mapped_column(Text)

    # --- Staff feedback on the suggested reply (reset when the AI writes a new reply) ---
    reply_rating: Mapped[str | None] = mapped_column(String(10), index=True)  # good/bad
    reply_note: Mapped[str | None] = mapped_column(Text)
    reply_rated_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    analyzed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class DashboardAuth(Base):
    """The dashboard password (one row, id=1). Empty table = use DASHBOARD_PASSWORD from .env.
    Only hashes are stored, never the password or the reset code itself."""

    __tablename__ = "dashboard_auth"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    changed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    # --- "Forgot password": a 6-digit code emailed to the admin ---
    reset_code_hash: Mapped[str | None] = mapped_column(String(255))
    reset_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    reset_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    reset_attempts: Mapped[int | None] = mapped_column(Integer)

    # --- Slow down password guessing ---
    failed_logins: Mapped[int | None] = mapped_column(Integer)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime)
