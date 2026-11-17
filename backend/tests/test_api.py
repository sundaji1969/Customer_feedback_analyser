"""API tests. Run from the backend folder:  python -m pytest"""
import csv
import io
from pathlib import Path

from conftest import make_csv, upload

SAMPLE_ROWS = [
    {"review_id": "R1", "date": "2026-01-05", "platform": "Google", "rating": 5,
     "review_text": "Lovely food, great service"},
    {"review_id": "R2", "date": "2026-02-10", "platform": "Swiggy", "rating": 2,
     "review_text": "Delivery romba late, food cold"},
    {"review_id": "R3", "date": "2026-03-15", "platform": "Zomato", "rating": 1,
     "review_text": "After eating my son got vomiting"},
    {"review_id": "R4", "date": "2026-03-20", "platform": "Google", "rating": 5,
     "review_text": "சாப்பாடு மிகவும் சுவையாக இருந்தது"},
]


def by_id(reviews):
    return {r["review_id"]: r for r in reviews}


# ---------- health ----------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# ---------- upload ----------

def test_upload_saves_and_tags_reviews(client, fake_ai):
    res = upload(client, make_csv(SAMPLE_ROWS))
    assert res.status_code == 200
    assert res.json() == {
        "rows_in_file": 4, "new_reviews": 4, "updated_reviews": 0,
        "analyzed": 4, "failed": 0, "errors": [], "alert": None,
    }

    reviews = by_id(client.get("/reviews").json())
    assert set(reviews) == {"R1", "R2", "R3", "R4"}
    assert reviews["R3"]["urgency"] == "HIGH"
    assert reviews["R2"]["language"] == "Tanglish"
    assert reviews["R4"]["language"] == "Tamil"
    assert reviews["R4"]["review_text"] == "சாப்பாடு மிகவும் சுவையாக இருந்தது"  # Tamil kept intact
    assert all(r["analyzed_at"] for r in reviews.values())


def test_reupload_same_file_does_not_call_ai_again(client, fake_ai):
    upload(client, make_csv(SAMPLE_ROWS))
    calls_after_first = fake_ai.analyzed_count

    res = upload(client, make_csv(SAMPLE_ROWS)).json()
    assert res["new_reviews"] == 0
    assert res["updated_reviews"] == 4
    assert res["analyzed"] == 0
    assert fake_ai.analyzed_count == calls_after_first  # no extra (paid) AI calls


def test_changed_text_is_analyzed_again(client, fake_ai):
    upload(client, make_csv(SAMPLE_ROWS))
    changed = [dict(SAMPLE_ROWS[0], review_text="Order was very late today")] + SAMPLE_ROWS[1:]

    res = upload(client, make_csv(changed)).json()
    assert res["analyzed"] == 1
    r1 = by_id(client.get("/reviews").json())["R1"]
    assert r1["review_text"] == "Order was very late today"
    assert r1["sentiment"] == "negative"


def test_rejects_non_csv_file(client):
    res = upload(client, b"hello", filename="reviews.txt")
    assert res.status_code == 400
    assert ".csv" in res.json()["detail"]


def test_rejects_missing_columns(client):
    res = upload(client, b"review_id,review_text\nR1,hi\n")
    assert res.status_code == 400
    assert "date" in res.json()["detail"] and "rating" in res.json()["detail"]


def test_rejects_non_utf8_file(client):
    bad = "review_id,date,platform,rating,review_text\nR1,2026-01-01,G,5,caf\xe9\n".encode("latin-1")
    res = upload(client, bad)
    assert res.status_code == 400
    assert "UTF-8" in res.json()["detail"]


def test_rejects_too_many_rows(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "MAX_ROWS_PER_UPLOAD", 2)
    res = upload(client, make_csv(SAMPLE_ROWS))
    assert res.status_code == 400
    assert "Too many rows" in res.json()["detail"]


def test_csv_cleanup(client):
    """Messy CSV: header case/spaces, Excel BOM, blank rows, duplicate IDs, odd ratings/dates."""
    raw = (
        "﻿ Review_ID ,Date,Platform,Rating,Review_Text\n"
        "R1,05/01/2026,Google,4.6,First version\n"
        "R1,05/01/2026,Google,4.6,Second version wins\n"   # duplicate id -> keep last
        ",2026-01-01,Google,5,No id so skipped\n"           # blank id -> skipped
        "R2,2026-01-01,Google,5,\n"                         # blank text -> skipped
        "R3,not-a-date,,abc,Odd values\n"                   # bad date/rating -> empty
    ).encode("utf-8")
    res = upload(client, raw).json()
    assert res["rows_in_file"] == 2

    reviews = by_id(client.get("/reviews").json())
    assert set(reviews) == {"R1", "R3"}
    assert reviews["R1"]["review_text"] == "Second version wins"
    assert reviews["R1"]["rating"] == 5                     # 4.6 rounded
    assert reviews["R1"]["date"] == "2026-01-05"            # day-first (Indian format)
    assert reviews["R3"]["date"] is None
    assert reviews["R3"]["rating"] is None
    assert reviews["R3"]["platform"] is None


# ---------- AI failures and retry ----------

def test_failed_reviews_are_reported_and_can_be_retried(client, fake_ai):
    fake_ai.fail_texts = {"Lovely food, great service"}
    res = upload(client, make_csv(SAMPLE_ROWS)).json()
    assert res["analyzed"] == 3
    assert res["failed"] == 1
    assert res["errors"][0].startswith("R1:")
    assert by_id(client.get("/reviews").json())["R1"]["analyzed_at"] is None

    fake_ai.fail_texts = set()  # AI works again
    retry = client.post("/reviews/analyze-pending").json()
    assert retry == {"analyzed": 1, "failed": 0, "errors": [], "alert": None}
    assert by_id(client.get("/reviews").json())["R1"]["sentiment"] == "positive"


def test_missing_api_key_gives_clear_error(client, monkeypatch):
    from app import main

    def no_key(reviews, max_concurrency=5):
        raise RuntimeError("OPENAI_API_KEY is missing. Put your key in the .env file.")

    monkeypatch.setattr(main, "analyze_reviews", no_key)
    res = upload(client, make_csv(SAMPLE_ROWS[:1]))
    assert res.status_code == 500
    assert "OPENAI_API_KEY" in res.json()["detail"]


def test_large_upload_is_processed_in_chunks(client, fake_ai):
    rows = [{"review_id": f"R{i}", "date": "2026-01-01", "platform": "Google",
             "rating": 5, "review_text": f"Nice visit number {i}"} for i in range(45)]
    res = upload(client, make_csv(rows)).json()
    assert res["analyzed"] == 45
    assert [len(c) for c in fake_ai.calls] == [20, 20, 5]


# ---------- listing and filters ----------

def test_filters(client):
    upload(client, make_csv(SAMPLE_ROWS))

    def ids(query):
        return sorted(r["review_id"] for r in client.get(f"/reviews?{query}").json())

    assert ids("urgency=high") == ["R3"]                      # case-insensitive
    assert ids("sentiment=NEGATIVE") == ["R2", "R3"]
    assert ids("category=Delivery") == ["R2"]
    assert ids("platform=Google") == ["R1", "R4"]
    assert ids("language=Tamil") == ["R4"]
    assert ids("start_date=2026-02-01&end_date=2026-03-15") == ["R2", "R3"]
    assert ids("platform=Google&sentiment=positive") == ["R1", "R4"]
    assert ids("platform=Nowhere") == []


def test_list_is_newest_first_and_respects_limit(client):
    upload(client, make_csv(SAMPLE_ROWS))
    assert [r["review_id"] for r in client.get("/reviews").json()] == ["R4", "R3", "R2", "R1"]
    assert len(client.get("/reviews?limit=2").json()) == 2


def test_bad_date_filter_is_rejected(client):
    assert client.get("/reviews?start_date=yesterday").status_code == 422


# ---------- export ----------

def test_export_csv(client):
    upload(client, make_csv(SAMPLE_ROWS))
    res = client.get("/reviews/export?platform=Google")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    assert res.content.startswith(b"\xef\xbb\xbf")  # BOM so Excel shows Tamil correctly

    rows = list(csv.DictReader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert sorted(r["review_id"] for r in rows) == ["R1", "R4"]
    assert "suggested_reply" in rows[0]
    assert any(r["review_text"] == "சாப்பாடு மிகவும் சுவையாக இருந்தது" for r in rows)


def test_export_empty_still_has_header(client):
    res = client.get("/reviews/export")
    header = res.content.decode("utf-8-sig").splitlines()[0]
    assert header.startswith("review_id,date,platform,rating,review_text")


def test_export_is_excel_safe(client):
    """Customer text starting with = + - @ must not become an Excel formula."""
    rows = [
        {"review_id": "X1", "date": "2026-01-01", "platform": "Google", "rating": 1,
         "review_text": '=HYPERLINK("http://evil.example","click")'},
        {"review_id": "X2", "date": "2026-01-02", "platform": "@Swiggy", "rating": 2,
         "review_text": "-ve experience, food late"},
        {"review_id": "X3", "date": "2026-01-03", "platform": "Zomato", "rating": 5,
         "review_text": "Nice food, 5 stars = happy"},   # '=' not at the start: unchanged
    ]
    upload(client, make_csv(rows))
    res = client.get("/reviews/export")
    assert b"\r\n" in res.content                       # Windows line endings for Excel
    got = by_id(csv.DictReader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert got["X1"]["review_text"] == "'" + rows[0]["review_text"]
    assert got["X2"]["review_text"] == "'-ve experience, food late"
    assert got["X2"]["platform"] == "'@Swiggy"
    assert got["X3"]["review_text"] == "Nice food, 5 stars = happy"
    assert got["X3"]["rating"] == "5"                      # numbers are untouched


# ---------- 200+ rows and field quality ----------

ALLOWED = {
    "sentiment": {"positive", "neutral", "negative"},
    "category": {"Product Quality", "Delivery", "Customer Service", "Pricing", "App/Website",
                 "Payment/Refund", "Staff Behaviour", "Cleanliness", "Other"},
    "urgency": {"HIGH", "MEDIUM", "LOW"},
    "language": {"English", "Tamil", "Tanglish", "Other"},
}


def test_250_rows_upload_and_every_review_gets_6_valid_fields(client, fake_ai):
    texts = ["Food was great", "Delivery romba late", "Son got vomiting after eating",
             "சாப்பாடு மிகவும் சுவையாக இருந்தது"]
    rows = [{"review_id": f"B{i:03d}", "date": f"2026-10-{i % 28 + 1:02d}", "platform": "Google",
             "rating": i % 5 + 1, "review_text": f"{texts[i % 4]} #{i}"} for i in range(250)]
    res = upload(client, make_csv(rows))
    assert res.status_code == 200
    assert res.json()["analyzed"] == 250 and res.json()["failed"] == 0
    assert max(len(c) for c in fake_ai.calls) <= 20         # saved in chunks, never all at once

    reviews = client.get("/reviews?limit=20000").json()
    assert len(reviews) == 250
    for r in reviews:
        for field, allowed in ALLOWED.items():
            assert r[field] in allowed, (r["review_id"], field, r[field])
        assert r["summary"].strip() and r["suggested_reply"].strip()
        assert not any("஀" <= ch <= "௿" for ch in r["summary"])   # English summary

    high = client.get("/reviews?urgency=HIGH&limit=20000").json()
    assert len(high) == sum(1 for r in reviews if r["urgency"] == "HIGH") > 0
    assert {r["urgency"] for r in high} == {"HIGH"}


# ---------- delete ----------

def test_delete_needs_confirm(client):
    upload(client, make_csv(SAMPLE_ROWS))
    assert client.delete("/reviews").status_code == 400
    assert len(client.get("/reviews").json()) == 4

    assert client.delete("/reviews?confirm=true").json() == {"deleted": 4}
    assert client.get("/reviews").json() == []


# ---------- the real sample file ----------

def test_sample_file_uploads_cleanly(client):
    sample = Path(__file__).resolve().parents[2] / "data" / "sample_reviews.csv"
    res = upload(client, sample.read_bytes(), filename="sample_reviews.csv").json()
    assert res["rows_in_file"] == 30
    assert res["new_reviews"] == 30
    assert res["failed"] == 0
    # Regression: ISO dates used to be read day-first (2026-10-01 stored as 10 Jan)
    assert by_id(client.get("/reviews").json())["R001"]["date"] == "2026-10-01"
