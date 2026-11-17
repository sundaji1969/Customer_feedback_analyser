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
    assert [t.label for t in at.tabs] == ["🚨 Action queue", "📊 Insights", "📈 Trends", "⭐ Reply quality", "📋 All reviews"]
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
    assert "📝 Reviews" not in [m.label for m in at.metric]  # no trend numbers


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
    assert not any(t.label == "Password" for t in at.text_input)  # no password box
    assert len(at.tabs) == 5


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
        assert len(at.tabs) == 5           # logged in

        next(b for b in at.button if b.label == "Log out").click().run()
        assert not at.tabs                 # logged out again


# ---------- search ----------

def test_search_box_narrows_the_view():
    at = run_app(REVIEWS)
    with patch("requests.get", side_effect=fake_get(REVIEWS)):
        box = next(t for t in at.text_input if t.label == "🔍 Search")
        box.input("summary 3").run()
    assert not at.exception
    assert "showing <b>1</b> of 5 reviews" in markdown_text(at)


def test_search_with_no_match_does_not_crash():
    at = run_app(REVIEWS)
    with patch("requests.get", side_effect=fake_get(REVIEWS)):
        next(t for t in at.text_input if t.label == "🔍 Search").input("no such words").run()
    assert not at.exception
    assert "showing <b>0</b> of 5 reviews" in markdown_text(at)


# ---------- reply ratings ----------

RATED = [
    {**REVIEWS[0], "reply_rating": "good", "reply_note": None},
    {**REVIEWS[1], "reply_rating": "bad", "reply_note": "Did not ask how they are"},
    *[{**r, "reply_rating": None, "reply_note": None} for r in REVIEWS[2:]],
]


def test_reply_quality_tab_shows_numbers_and_bad_replies():
    at = run_app(RATED)
    assert not at.exception, [e.value for e in at.exception]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["📝 Replies rated"] == "2 of 5"
    assert metrics["👍 Rated good"] == "50%"
    assert metrics["👎 Rated bad"] == "1"
    assert any("Rate more replies (3 not rated yet)" in s.value for s in at.subheader)


def test_rating_button_sends_rating_and_note_to_backend():
    at = run_app(RATED)
    posted = MagicMock(return_value=MagicMock(ok=True, status_code=200))
    with patch("requests.get", side_effect=fake_get(RATED)), patch("requests.post", posted):
        at.text_input(key="note-queue-R3").input("too formal")
        at.button(key="bad-queue-R3").click().run()
    assert not at.exception
    url, kwargs = posted.call_args.args[0], posted.call_args.kwargs
    assert url.endswith("/reviews/rate-reply")
    assert kwargs["json"] == {"review_id": "R3", "rating": "bad", "note": "too formal"}


def test_good_button_sends_no_note():
    at = run_app(RATED)
    posted = MagicMock(return_value=MagicMock(ok=True, status_code=200))
    with patch("requests.get", side_effect=fake_get(RATED)), patch("requests.post", posted):
        at.button(key="good-rate-R3").click().run()
    assert posted.call_args.kwargs["json"] == {"review_id": "R3", "rating": "good", "note": None}


def test_rated_reply_shows_its_rating_and_can_be_cleared():
    at = run_app(RATED)
    # R2 (HIGH, in the queue) is rated bad with a note
    assert any(c.value == "Rated: 👎 bad — “Did not ask how they are”" for c in at.caption)
    assert not at.button(key="good-queue-R2").disabled
    posted = MagicMock(return_value=MagicMock(ok=True, status_code=200))
    with patch("requests.get", side_effect=fake_get(RATED)), patch("requests.post", posted):
        at.button(key="clear-queue-R2").click().run()
    assert posted.call_args.kwargs["json"] == {"review_id": "R2", "rating": None, "note": None}
    # unrated replies have no Clear button
    assert not any(b.key == "clear-queue-R3" for b in at.button)


def test_rated_good_reply_cannot_be_rated_good_again():
    rows = [{**r, "reply_rating": "good" if r["review_id"] == "R3" else None, "reply_note": None} for r in REVIEWS]
    at = run_app(rows)
    assert at.button(key="good-queue-R3").disabled
    assert not at.button(key="bad-queue-R3").disabled


def test_dashboard_works_with_backend_that_has_no_ratings_yet():
    at = run_app(REVIEWS)  # no reply_rating / reply_note fields at all
    assert not at.exception
    assert {m.label: m.value for m in at.metric}["📝 Replies rated"] == "0 of 5"
