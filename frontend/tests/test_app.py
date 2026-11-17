"""Smoke tests: run the whole dashboard against a fake backend (no servers needed)."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(autouse=True)
def fresh_cache():
    """The app caches backend data for 60s; start every test without it."""
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def review(i, date, sentiment, urgency, rating=4, language="English"):
    return {
        "review_id": f"R{i}", "date": date, "platform": "Google", "rating": rating,
        "review_text": f"Review {i}", "sentiment": sentiment, "category": "Delivery",
        "urgency": urgency, "language": language, "summary": f"Summary {i}",
        "suggested_reply": "Thank you!", "analyzed_at": "2026-11-17T10:00:00",
    }


REVIEWS = [
    review(1, "2026-10-05", "positive", "LOW", 5),
    review(2, "2026-10-07", "negative", "HIGH", 1),
    review(3, "2026-10-14", "negative", "MEDIUM", 2, "Tanglish"),
    review(4, "2026-10-21", "neutral", "LOW", 3, "Tamil"),
    review(5, None, "positive", "LOW", 5),
]


def fake_get(reviews):
    def get(url, *args, **kwargs):
        resp = MagicMock(ok=True, status_code=200)
        resp.json.return_value = {"status": "ok"} if url.endswith("/health") else reviews
        return resp
    return get


def run_app(reviews):
    with patch("requests.get", side_effect=fake_get(reviews)):
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
    return at


def markdown_text(at):
    return " ".join(m.value for m in at.markdown)


def test_dashboard_renders_all_tabs_without_errors():
    at = run_app(REVIEWS)
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error
    assert [t.label for t in at.tabs] == ["🚨 Action queue", "📊 Insights", "📈 Trends", "📋 All reviews"]
    assert "showing <b>5</b> of 5 reviews" in markdown_text(at)


def test_trends_tab_compares_latest_week():
    at = run_app(REVIEWS)
    metrics = {m.label: (m.value, m.delta) for m in at.metric}
    # latest week (19 Oct): 1 neutral review rated 3; week before (12 Oct): 1 negative rated 2
    assert metrics["📝 Reviews"] == ("1", "+0")
    assert metrics["⭐ Avg rating"] == ("3.0★", "+1.0★")
    assert metrics["😞 Negative"] == ("0%", "-100 pts")
    assert metrics["🚨 High urgency"] == ("0", "+0")
    assert "week of 19 Oct 2026" in markdown_text(at)


def test_trends_tab_explains_when_not_enough_weeks():
    at = run_app(REVIEWS[:2])  # both in the same week
    assert not at.exception
    assert any("at least 2 different weeks" in i.value for i in at.info)
    assert not at.metric


def test_empty_database_shows_upload_hint():
    at = run_app([])
    assert not at.exception
    assert any("No reviews yet" in i.value for i in at.info)


def test_filter_narrows_the_view():
    at = run_app(REVIEWS)
    urgency = next(m for m in at.multiselect if m.label == "Urgency")
    with patch("requests.get", side_effect=fake_get(REVIEWS)):
        urgency.select("HIGH").run()
    assert not at.exception
    assert "showing <b>1</b> of 5 reviews" in markdown_text(at)


def test_backend_down_shows_clear_error():
    with patch("requests.get", side_effect=requests.ConnectionError("refused")):
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
    assert any("Cannot reach the backend" in e.value for e in at.error)


# ---------- password ----------

def test_no_password_set_means_no_login(monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    at = run_app(REVIEWS)
    assert not at.text_input  # no password box
    assert len(at.tabs) == 4


def test_password_protects_dashboard(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "s3cret-pass")
    with patch("requests.get", side_effect=fake_get(REVIEWS)) as get:
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
        assert not at.tabs                 # dashboard hidden
        assert get.call_count == 0         # and no data loaded before login

        at.text_input[0].input("wrong")    # type + submit together, like a browser form
        at.button[0].click().run()
        assert any("Wrong password" in e.value for e in at.error)
        assert not at.tabs

        at.text_input[0].input("s3cret-pass")
        at.button[0].click().run()
        assert not at.exception
        assert len(at.tabs) == 4           # logged in

        next(b for b in at.button if b.label == "Log out").click().run()
        assert not at.tabs                 # logged out again
