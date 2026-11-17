"""Tests for the week-by-week trend numbers."""
import pandas as pd
import pytest

from trends import latest_change, weekly_sentiment, weekly_trends


def reviews(rows):
    df = pd.DataFrame(rows, columns=["date", "rating", "sentiment", "urgency"])
    df["date"] = pd.to_datetime(df["date"])
    return df


# Week of Mon 5 Oct 2026: 2 reviews. Week of 12 Oct: none. Week of 19 Oct: 3 reviews.
DATA = reviews([
    ("2026-10-05", 5, "positive", "LOW"),      # Monday
    ("2026-10-11", 1, "negative", "HIGH"),     # Sunday -> same week
    ("2026-10-19", 2, "negative", "MEDIUM"),
    ("2026-10-21", 4, "neutral", "LOW"),
    ("2026-10-25", None, "negative", "HIGH"),  # no rating
    (None, 1, "negative", "HIGH"),             # no date -> ignored
])


def test_weekly_numbers():
    t = weekly_trends(DATA)
    assert list(t.index.strftime("%Y-%m-%d")) == ["2026-10-05", "2026-10-12", "2026-10-19"]
    assert t["reviews"].tolist() == [2, 0, 3]
    assert t["high_urgency"].tolist() == [1, 0, 1]
    assert t.loc["2026-10-05", "avg_rating"] == 3.0
    assert t.loc["2026-10-19", "avg_rating"] == 3.0          # missing rating not counted as 0
    assert t.loc["2026-10-05", "pct_negative"] == 50.0
    assert t.loc["2026-10-19", "pct_negative"] == pytest.approx(200 / 3)


def test_empty_week_is_kept_but_has_no_average():
    t = weekly_trends(DATA)
    assert pd.isna(t.loc["2026-10-12", "avg_rating"])
    assert pd.isna(t.loc["2026-10-12", "pct_negative"])


def test_no_dates_gives_empty_table():
    t = weekly_trends(reviews([(None, 5, "positive", "LOW")]))
    assert t.empty
    assert list(t.columns) == ["reviews", "avg_rating", "pct_negative", "high_urgency"]


def test_weekly_sentiment_fills_every_week_and_sentiment():
    s = weekly_sentiment(DATA)
    assert len(s) == 3 * 3  # 3 weeks x 3 sentiments
    counts = s.set_index(["week", "sentiment"])["count"]
    assert counts[(pd.Timestamp("2026-10-19"), "negative")] == 2
    assert counts[(pd.Timestamp("2026-10-12"), "positive")] == 0
    assert s["count"].sum() == 5  # undated review left out


def test_latest_change_compares_last_two_weeks():
    t = weekly_trends(DATA.iloc[[0, 1, 2, 3, 4]].assign(
        date=pd.to_datetime(["2026-10-12", "2026-10-13", "2026-10-19", "2026-10-21", "2026-10-25"])))
    c = latest_change(t)
    assert c["week"] == pd.Timestamp("2026-10-19")
    assert c["reviews"] == (3, 1)
    assert c["high_urgency"] == (1, 0)
    assert c["avg_rating"] == (3.0, 0.0)
    assert c["pct_negative"][1] == pytest.approx(200 / 3 - 50)


def test_latest_change_after_empty_week_has_no_rating_change():
    c = latest_change(weekly_trends(DATA.iloc[:4]).iloc[:3])  # weeks: 5 Oct, 12 Oct (empty), 19 Oct
    assert c["reviews"] == (2, 2)
    assert c["avg_rating"] == (3.0, None)  # can't compare against an empty week


def test_latest_change_needs_two_weeks():
    assert latest_change(weekly_trends(DATA.iloc[:2])) is None
