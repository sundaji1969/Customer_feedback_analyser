"""Database tables."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # --- Columns from the uploaded CSV ---
    review_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    date: Mapped[date | None] = mapped_column(Date, index=True)
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

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime)
