"""Data shapes: what the AI must return, and what the API sends back."""
import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Sentiment = Literal["positive", "neutral", "negative"]
Urgency = Literal["HIGH", "MEDIUM", "LOW"]
Language = Literal["English", "Tamil", "Tanglish", "Other"]
TAMIL_SCRIPT = re.compile(r"[஀-௿]")

Category = Literal[
    "Product Quality",
    "Delivery",
    "Customer Service",
    "Pricing",
    "App/Website",
    "Payment/Refund",
    "Staff Behaviour",
    "Cleanliness",
    "Other",
]


class ReviewTags(BaseModel):
    """What the AI must return in the tagging step for ONE review."""

    sentiment: Sentiment = Field(description="Overall feeling of the customer.")
    category: Category = Field(description="Main topic of the review.")
    urgency: Urgency = Field(description="How fast the business must respond.")
    language: Language = Field(description="Language the review is written in.")
    summary: str = Field(description="One short sentence in ENGLISH summarising the review.")

    @field_validator("summary")
    @classmethod
    def summary_is_english(cls, value: str) -> str:
        """Every summary must be real English text, even for Tamil/Tanglish reviews."""
        value = value.strip()
        if not value:
            raise ValueError("summary is empty")
        if TAMIL_SCRIPT.search(value):
            raise ValueError("summary must be in English, not Tamil script")
        if not re.search(r"[A-Za-z]{2,}", value):
            raise ValueError("summary must be English text")
        return value


class ReviewAnalysis(ReviewTags):
    """Tags + suggested reply for ONE review (what gets saved)."""

    suggested_reply: str = Field(
        description="Polite reply to the customer, in the SAME language/style as the review."
    )

    @field_validator("suggested_reply")
    @classmethod
    def reply_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("suggested_reply is empty")
        return value


class ReviewOut(BaseModel):
    """One review as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    review_id: str
    date: dt.date | None
    platform: str | None
    rating: int | None
    review_text: str
    sentiment: str | None
    category: str | None
    urgency: str | None
    language: str | None
    summary: str | None
    suggested_reply: str | None
    analyzed_at: dt.datetime | None
    reply_rating: str | None = None
    reply_note: str | None = None


class ReplyRating(BaseModel):
    """Staff verdict on one suggested reply. rating=None clears it."""

    review_id: str
    rating: Literal["good", "bad"] | None
    note: str | None = Field(None, max_length=1000)

    @field_validator("note")
    @classmethod
    def blank_note_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class UploadResult(BaseModel):
    rows_in_file: int
    new_reviews: int
    updated_reviews: int
    analyzed: int
    failed: int
    errors: list[str] = []
    alert: str | None = None  # what happened with the high-urgency email, if one was due
