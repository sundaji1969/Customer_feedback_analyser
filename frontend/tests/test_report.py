"""Report numbers are calculated with pandas from the table, and the CSV is safe for Excel."""
import csv
import io
import re
from unittest.mock import patch

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from report import excel_csv, excel_safe, summary_numbers
from test_app import APP, fake_get, review

TABLE = pd.DataFrame([
    review(1, "2026-10-05", "positive", "LOW", 5),
    review(2, "2026-10-06", "negative", "HIGH", 1),
    review(3, "2026-10-07", "negative", "HIGH", 2),
    review(4, "2026-10-08", "neutral", "MEDIUM", None),     # no rating
    review(5, "2026-10-09", "positive", "LOW", 4),
    {**review(6, "2026-10-10", None, None, 3), "analyzed_at": None, "summary": None},  # not analyzed yet
])


def test_summary_numbers_match_the_table_exactly():
    n = summary_numbers(TABLE)
    assert n["reviews"] == 6
    assert n["analyzed"] == 5
    assert n["avg_rating"] == pytest.approx((5 + 1 + 2 + 4 + 3) / 5)   # missing rating not counted as 0
    assert n["pct_positive"] == pytest.approx(2 / 5 * 100)             # of analyzed reviews
    assert n["pct_negative"] == pytest.approx(2 / 5 * 100)
    assert n["high_urgency"] == 2


def test_summary_numbers_for_empty_selection():
    n = summary_numbers(TABLE.iloc[0:0])
    assert n == {"reviews": 0, "analyzed": 0, "avg_rating": None,
                 "pct_positive": 0.0, "pct_negative": 0.0, "high_urgency": 0}


@pytest.fixture(autouse=True)
def fresh_cache():
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def kpi_cards(at) -> dict:
    html = next(m.value for m in at.markdown if 'class="kpis"' in m.value)
    return dict(re.findall(r'<div class="label">([^<]+)</div><div class="value">([^<]+)</div>', html))


@pytest.mark.parametrize("pick_high", [False, True])
def test_dashboard_cards_match_the_all_reviews_table(pick_high):
    """The numbers on screen are recomputed here from the table the dashboard shows."""
    data = TABLE.astype(object).where(TABLE.notna(), None).to_dict("records")
    with patch("requests.get", side_effect=fake_get(data)):
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
        if pick_high:
            next(m for m in at.multiselect if m.label == "Urgency").select("HIGH").run()
    assert not at.exception

    table = at.dataframe[0].value                     # the "All reviews" table on screen
    analyzed = table[table["sentiment"].notna()]
    cards = kpi_cards(at)
    assert cards["📝 Reviews"] == str(len(table))
    assert cards["⭐ Avg rating"] == f"{table['rating'].astype(float).mean():.1f}★"
    assert cards["😊 Positive"] == f"{(analyzed['sentiment'] == 'positive').mean() * 100:.0f}%"
    assert cards["😞 Negative"] == f"{(analyzed['sentiment'] == 'negative').mean() * 100:.0f}%"
    assert cards["🚨 High urgency"] == str((table["urgency"] == "HIGH").sum())
    if pick_high:
        assert set(table["urgency"]) == {"HIGH"} and len(table) == 2


# ---------- Excel-safe CSV ----------

@pytest.mark.parametrize("value, expected", [
    ("=1+1", "'=1+1"),
    ("+91 98765 43210", "'+91 98765 43210"),
    ("-ve service", "'-ve service"),
    ("@Swiggy", "'@Swiggy"),
    ("Food = good", "Food = good"),
    ("சாப்பாடு நன்று", "சாப்பாடு நன்று"),
    (5, 5),
    (None, None),
])
def test_excel_safe(value, expected):
    assert excel_safe(value) == expected


def test_excel_csv_keeps_tamil_and_blocks_formulas():
    df = pd.DataFrame({
        "review_id": ["R1", "R2"],
        "rating": [5, None],
        "review_text": ['=HYPERLINK("http://x","y")', "சாப்பாடு நன்று, \"semma\"\nnew line"],
    })
    data = excel_csv(df)
    assert data.startswith(b"\xef\xbb\xbf")           # BOM: Excel reads it as UTF-8
    assert b"\r\n" in data                            # Windows line endings
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline="")))
    assert rows[0]["review_text"].startswith("'=")
    assert rows[1]["review_text"] == "சாப்பாடு நன்று, \"semma\"\nnew line"   # quotes/newlines survive
    assert rows[1]["rating"] == ""


# ---------- search ----------

from report import reply_quality, search  # noqa: E402

SEARCH_TABLE = pd.DataFrame([
    {"review_id": "R001", "review_text": "Biryani was cold", "summary": "Food arrived cold.", "suggested_reply": "Sorry!"},
    {"review_id": "R002", "review_text": "சாப்பாடு குளிர்ந்து இருந்தது", "summary": "The food was COLD and late.",
     "suggested_reply": "மன்னிக்கவும்"},
    {"review_id": "R003", "review_text": "Refund (still) pending?", "summary": None, "suggested_reply": None},
])


@pytest.mark.parametrize("text, expected", [
    ("", ["R001", "R002", "R003"]),          # empty search shows everything
    ("   ", ["R001", "R002", "R003"]),
    ("cold", ["R001", "R002"]),              # Tamil review found through its English summary
    ("COLD late", ["R002"]),                 # all words must match, any case, any order
    ("late cold", ["R002"]),
    ("r003", ["R003"]),                      # by review id
    ("(still) pending?", ["R003"]),          # brackets / ? are plain text, not regex
    ("குளிர்ந்து", ["R002"]),                # Tamil search
    ("மன்னிக்கவும்", ["R002"]),               # in the reply
    ("pizza", []),
])
def test_search(text, expected):
    assert search(SEARCH_TABLE, text)["review_id"].tolist() == expected


# ---------- reply quality ----------

def test_reply_quality_counts_rated_replies_only():
    table = pd.DataFrame([
        {"language": "English", "reply_rating": "good"},
        {"language": "English", "reply_rating": "bad"},
        {"language": "Tanglish", "reply_rating": "good"},
        {"language": "Tanglish", "reply_rating": None},   # not rated: not good, not bad
    ])
    q = reply_quality(table)
    assert (q["replies"], q["rated"], q["bad"]) == (4, 3, 1)
    assert q["pct_good"] == pytest.approx(2 / 3 * 100)
    by_lang = q["by_language"].set_index("language")
    assert by_lang.loc["English", "pct_good"] == 50 and by_lang.loc["Tanglish", "pct_good"] == 100
    assert by_lang.loc["English", "label"] == "50% of 2"


def test_reply_quality_with_nothing_rated():
    q = reply_quality(pd.DataFrame({"language": ["English"], "reply_rating": [None]}))
    assert (q["rated"], q["pct_good"], q["by_language"]) == (0, None, None)
