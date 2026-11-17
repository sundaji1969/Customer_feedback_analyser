"""Reply ratings, the database upgrade for them, and high-urgency email alerts."""
import csv
import io
import smtplib

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app import alerts
from app.database import init_db
from conftest import make_csv, upload

ROWS = [
    {"review_id": "R1", "date": "2026-01-05", "platform": "Google", "rating": 5, "review_text": "Lovely food"},
    {"review_id": "R2", "date": "2026-02-10", "platform": "Swiggy", "rating": 1,
     "review_text": "After eating my son got vomiting"},                               # HIGH
    {"review_id": "R3", "date": "2026-03-15", "platform": "Zomato", "rating": 1,
     "review_text": "சாப்பாடு சாப்பிட்டு vomiting ஆனது"},                                 # HIGH, Tamil
]


def review(client, review_id):
    return next(r for r in client.get("/reviews").json() if r["review_id"] == review_id)


def rate(client, review_id, rating, note=None):
    return client.post("/reviews/rate-reply", json={"review_id": review_id, "rating": rating, "note": note})


# ---------- reply ratings ----------

def test_new_reviews_are_unrated(client):
    upload(client, make_csv(ROWS))
    r = review(client, "R1")
    assert r["reply_rating"] is None and r["reply_note"] is None


def test_rate_good_then_bad_with_note_then_clear(client):
    upload(client, make_csv(ROWS))

    res = rate(client, "R1", "good")
    assert res.status_code == 200 and res.json()["reply_rating"] == "good"

    rate(client, "R1", "bad", "  Too formal for Tanglish  ")
    r = review(client, "R1")
    assert (r["reply_rating"], r["reply_note"]) == ("bad", "Too formal for Tanglish")  # trimmed

    rate(client, "R1", None, "ignored when clearing")
    r = review(client, "R1")
    assert (r["reply_rating"], r["reply_note"]) == (None, None)


def test_blank_note_is_stored_as_empty(client):
    upload(client, make_csv(ROWS))
    rate(client, "R1", "bad", "   ")
    assert review(client, "R1")["reply_note"] is None


def test_rating_unknown_review_is_404(client):
    upload(client, make_csv(ROWS))
    res = rate(client, "NOPE", "good")
    assert res.status_code == 404 and "NOPE" in res.json()["detail"]


@pytest.mark.parametrize("bad_body", [
    {"review_id": "R1", "rating": "great"},          # only good/bad
    {"review_id": "R1", "rating": "bad", "note": "x" * 1001},  # note too long
    {"rating": "good"},                              # no review id
])
def test_invalid_rating_is_rejected(client, bad_body):
    upload(client, make_csv(ROWS))
    assert client.post("/reviews/rate-reply", json=bad_body).status_code == 422


def test_cannot_rate_a_review_without_reply(client, fake_ai):
    fake_ai.fail_texts.add("Lovely food")  # AI fails -> no reply yet
    upload(client, make_csv(ROWS))
    assert rate(client, "R1", "good").status_code == 400


def test_new_reply_clears_old_rating(client):
    upload(client, make_csv(ROWS))
    rate(client, "R1", "bad", "wrong tone")
    changed = [dict(ROWS[0], review_text="Order was very late")] + ROWS[1:]
    upload(client, make_csv(changed))  # text changed -> AI writes a new reply
    assert review(client, "R1")["reply_rating"] is None


def test_unchanged_reupload_keeps_rating(client):
    upload(client, make_csv(ROWS))
    rate(client, "R1", "good")
    upload(client, make_csv(ROWS))
    assert review(client, "R1")["reply_rating"] == "good"


def test_export_includes_ratings(client):
    upload(client, make_csv(ROWS))
    rate(client, "R2", "bad", "should ask how the son is")
    rows = list(csv.DictReader(io.StringIO(client.get("/reviews/export").content.decode("utf-8-sig"))))
    r2 = next(r for r in rows if r["review_id"] == "R2")
    assert (r2["reply_rating"], r2["reply_note"]) == ("bad", "should ask how the son is")


# ---------- database upgrade ----------

def test_existing_database_gets_new_columns_and_keeps_data():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:  # a reviews table as created by the previous version
        conn.execute(text(
            "CREATE TABLE reviews (id INTEGER PRIMARY KEY, review_id VARCHAR(100) UNIQUE, date DATE, "
            "platform VARCHAR(100), rating INTEGER, review_text TEXT, sentiment VARCHAR(20), "
            "category VARCHAR(50), urgency VARCHAR(10), language VARCHAR(20), summary TEXT, "
            "suggested_reply TEXT, created_at DATETIME, analyzed_at DATETIME)"))
        conn.execute(text("INSERT INTO reviews (review_id, review_text) VALUES ('OLD1', 'kept')"))

    init_db(engine)
    init_db(engine)  # running again (every restart) changes nothing

    columns = {c["name"] for c in inspect(engine).get_columns("reviews")}
    assert {"reply_rating", "reply_note", "reply_rated_at"} <= columns
    assert "ix_reviews_reply_rating" in {i["name"] for i in inspect(engine).get_indexes("reviews")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT review_text, reply_rating FROM reviews")).all() == [("kept", None)]


# ---------- high-urgency email alerts ----------

class FakeSMTP:
    """Stands in for smtplib.SMTP / SMTP_SSL and records what would be sent."""

    sent: list = []
    instances: list = []
    fail_with: Exception | None = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.ssl = host, port, context is not None
        self.started_tls, self.logged_in = False, None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def has_extn(self, name):
        return name == "starttls"

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        if FakeSMTP.fail_with:
            raise FakeSMTP.fail_with
        FakeSMTP.sent.append(msg)


@pytest.fixture
def mail(monkeypatch):
    FakeSMTP.sent, FakeSMTP.instances, FakeSMTP.fail_with = [], [], None
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(alerts.smtplib, "SMTP_SSL", FakeSMTP)
    for name, value in {"ALERT_EMAIL_TO": "owner@example.com, manager@example.com",
                        "SMTP_HOST": "smtp.example.com", "SMTP_USER": "bot@example.com",
                        "SMTP_PASSWORD": "app-password", "DASHBOARD_URL": "https://reviews.example.com"}.items():
        monkeypatch.setenv(name, value)
    return FakeSMTP


def test_upload_with_high_reviews_sends_one_email(client, mail):
    res = upload(client, make_csv(ROWS)).json()
    assert res["alert"] == "Alert email sent to owner@example.com, manager@example.com for 2 high-urgency reviews."
    assert len(mail.sent) == 1
    msg = mail.sent[0]
    assert msg["Subject"] == "ReviewLens: 2 HIGH-urgency reviews need attention"
    assert msg["To"] == "owner@example.com, manager@example.com"
    assert msg["From"] == "bot@example.com"
    body = msg.get_content()
    assert "R2 · Swiggy · 1★ · 10 Feb 2026" in body and "my son got vomiting" in body
    assert "சாப்பாடு சாப்பிட்டு vomiting ஆனது" in body          # Tamil intact
    assert "R1" not in body                                    # LOW review not included
    assert "https://reviews.example.com" in body
    server = mail.instances[0]
    assert (server.host, server.port, server.started_tls) == ("smtp.example.com", 587, True)
    assert server.logged_in == ("bot@example.com", "app-password")


def test_no_email_when_no_new_high_reviews(client, mail):
    upload(client, make_csv(ROWS[:1]))           # only a LOW review
    res = upload(client, make_csv(ROWS[:1])).json()
    assert res["alert"] is None and mail.sent == []


def test_reupload_does_not_alert_twice(client, mail):
    upload(client, make_csv(ROWS))
    res = upload(client, make_csv(ROWS)).json()  # same reviews, nothing newly analyzed
    assert res["alert"] is None and len(mail.sent) == 1


def test_alerts_off_when_not_configured(client, mail, monkeypatch):
    monkeypatch.delenv("ALERT_EMAIL_TO")
    res = upload(client, make_csv(ROWS)).json()
    assert res["alert"] is None and mail.sent == []


def test_mail_failure_does_not_break_upload(client, mail):
    mail.fail_with = smtplib.SMTPAuthenticationError(535, b"Bad credentials")
    res = upload(client, make_csv(ROWS))
    assert res.status_code == 200
    assert res.json()["analyzed"] == 3                       # reviews still saved and tagged
    assert res.json()["alert"].startswith("Alert email FAILED (SMTPAuthenticationError")
    assert len(client.get("/reviews").json()) == 3


def test_unreachable_mail_server_is_reported(client, mail):
    mail.fail_with = ConnectionRefusedError("refused")
    assert "FAILED (ConnectionRefusedError" in upload(client, make_csv(ROWS)).json()["alert"]


def test_port_465_uses_ssl(client, mail, monkeypatch):
    monkeypatch.setenv("SMTP_PORT", "465")
    upload(client, make_csv(ROWS))
    server = mail.instances[0]
    assert server.ssl and not server.started_tls


def test_bad_port_setting_is_reported(client, mail, monkeypatch):
    monkeypatch.setenv("SMTP_PORT", "five-eight-seven")
    res = upload(client, make_csv(ROWS))
    assert res.status_code == 200 and "SMTP_PORT must be a number" in res.json()["alert"]


def test_retry_endpoint_also_alerts(client, mail, fake_ai):
    fake_ai.fail_texts.add("After eating my son got vomiting")
    upload(client, make_csv(ROWS))                # R2 fails, R3 alerted
    fake_ai.fail_texts.clear()
    res = client.post("/reviews/analyze-pending").json()
    assert res["analyzed"] == 1 and "for 1 high-urgency review." in res["alert"]
    assert "R2" in mail.sent[-1].get_content()
