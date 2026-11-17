"""Shared test setup.

Tests run fully offline and free:
- the database is a throwaway in-memory SQLite (not your real PostgreSQL)
- the OpenAI call is replaced by a fake analyzer (no API key, no cost)
"""
import os

# Must be set BEFORE the app is imported, so the app never touches the real DB / OpenAI.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["OPENAI_API_KEY"] = "test-key-not-real"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import main  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.schemas import ReviewAnalysis  # noqa: E402


def fake_analysis(review: dict) -> ReviewAnalysis:
    """Predictable 'AI' tags based on simple keywords, so tests can check results."""
    text = review["review_text"].lower()
    if "vomit" in text or "poison" in text:
        sentiment, urgency, category = "negative", "HIGH", "Product Quality"
    elif "late" in text:
        sentiment, urgency, category = "negative", "MEDIUM", "Delivery"
    else:
        sentiment, urgency, category = "positive", "LOW", "Other"
    if any("஀" <= ch <= "௿" for ch in review["review_text"]):
        language = "Tamil"
    elif "romba" in text or "semma" in text:
        language = "Tanglish"
    else:
        language = "English"
    return ReviewAnalysis(
        sentiment=sentiment,
        category=category,
        urgency=urgency,
        language=language,
        summary=f"Summary of: {review['review_text'][:30]}",
        suggested_reply="Thank you for your feedback.",
    )


class FakeAnalyzer:
    """Stands in for app.analyzer.analyze_reviews. Records every call."""

    def __init__(self):
        self.calls: list[list[dict]] = []
        self.fail_texts: set[str] = set()  # reviews whose text is here will "fail"

    def __call__(self, reviews, max_concurrency=5):
        self.calls.append(reviews)
        return [
            RuntimeError("fake AI failure") if r["review_text"] in self.fail_texts else fake_analysis(r)
            for r in reviews
        ]

    @property
    def analyzed_count(self) -> int:
        return sum(len(c) for c in self.calls)


@pytest.fixture
def fake_ai(monkeypatch):
    fake = FakeAnalyzer()
    monkeypatch.setattr(main, "analyze_reviews", fake)
    return fake


@pytest.fixture
def client(fake_ai):
    """API client with a fresh, empty database for every test."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = override_get_db
    # Not using "with TestClient(...)" on purpose: that would run startup, which creates
    # tables on the app's own engine. Our test engine already has its tables.
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
    engine.dispose()


def make_csv(rows: list[dict], header: str = "review_id,date,platform,rating,review_text") -> bytes:
    """Build CSV bytes from a list of row dicts."""
    cols = header.split(",")
    lines = [header]
    for row in rows:
        values = []
        for col in cols:
            value = str(row.get(col, ""))
            if "," in value or '"' in value:
                value = '"' + value.replace('"', '""') + '"'
            values.append(value)
        lines.append(",".join(values))
    return ("\n".join(lines) + "\n").encode("utf-8")


def upload(client, csv_bytes: bytes, filename: str = "reviews.csv"):
    return client.post("/reviews/upload", files={"file": (filename, csv_bytes, "text/csv")})
