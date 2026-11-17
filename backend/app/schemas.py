"""Data shapes: what the AI must return, and what the API sends back."""
import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Sentiment = Literal["positive", "neutral", "negative"]
Urgency = Literal["HIGH", "MEDIUM", "LOW"]
Language = Literal["English", "Tamil", "Tanglish", "Other"]
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


class ReviewAnalysis(ReviewTags):
    """Tags + suggested reply for ONE review (what gets saved)."""

    suggested_reply: str = Field(
        description="Polite reply to the customer, in the SAME language/style as the review."
    )


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


class UploadResult(BaseModel):
    rows_in_file: int
    new_reviews: int
    updated_reviews: int
    analyzed: int
    failed: int
    errors: list[str] = []
