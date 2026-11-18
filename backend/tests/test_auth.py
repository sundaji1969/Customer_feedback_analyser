"""Dashboard password: login, change, forgot/reset by emailed code."""
import re
from datetime import datetime, timedelta

import pytest

from app import alerts, auth
from app.models import DashboardAuth
from test_ratings_alerts import FakeSMTP


@pytest.fixture(autouse=True)
def env_password(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "first-pass")


@pytest.fixture
def mail(monkeypatch):
    FakeSMTP.sent, FakeSMTP.instances, FakeSMTP.fail_with = [], [], None
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(alerts.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "bot@example.com")
    monkeypatch.setenv("RESET_EMAIL_TO", "owner@example.com")
    return FakeSMTP


def login(client, password):
    return client.post("/auth/login", json={"password": password})


def emailed_code(mail) -> str:
    return re.search(r"reset code is: (\d{6})", mail.sent[-1].get_content()).group(1)


def db_row(client):
    get_db = next(iter(client.app.dependency_overrides.values()))
    db = next(get_db())
    return db, db.get(DashboardAuth, 1)


# ---------- login ----------

def test_env_password_logs_in(client):
    assert login(client, "first-pass").json() == {"ok": True}
    res = login(client, "nope")
    assert res.status_code == 401 and res.json()["detail"] == "Wrong password."


def test_no_password_configured(client, monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD")
    assert login(client, "anything").status_code == 503


def test_too_many_wrong_passwords_locks_login(client):
    for _ in range(auth.MAX_FAILED_LOGINS):
        assert login(client, "wrong").status_code == 401
    res = login(client, "first-pass")  # even the right one is refused while locked
    assert res.status_code == 429 and "Try again in" in res.json()["detail"]


def test_lock_ends_after_wait(client):
    for _ in range(auth.MAX_FAILED_LOGINS):
        login(client, "wrong")
    db, row = db_row(client)
    row.locked_until = datetime.now() - timedelta(seconds=1)
    db.commit()
    assert login(client, "first-pass").status_code == 200


# ---------- change password ----------

def test_change_password(client):
    res = client.post("/auth/change-password",
                      json={"current_password": "first-pass", "new_password": "brand-new-1"})
    assert res.status_code == 200
    assert login(client, "brand-new-1").status_code == 200
    assert login(client, "first-pass").status_code == 401   # the .env password stops working
    _, row = db_row(client)
    assert "brand-new-1" not in row.password_hash            # only a hash is stored


def test_change_password_needs_right_current_password(client):
    res = client.post("/auth/change-password",
                      json={"current_password": "wrong", "new_password": "brand-new-1"})
    assert res.status_code == 401
    assert login(client, "first-pass").status_code == 200


def test_new_password_rules(client):
    short = client.post("/auth/change-password", json={"current_password": "first-pass", "new_password": "short"})
    assert short.status_code == 422
    same = client.post("/auth/change-password",
                       json={"current_password": "first-pass", "new_password": "first-pass"})
    assert same.status_code == 400


# ---------- forgot / reset ----------

def test_forgot_and_reset_password(client, mail):
    res = client.post("/auth/forgot-password")
    assert res.status_code == 200
    assert "o***@example.com" in res.json()["message"]
    assert mail.sent[0]["To"] == "owner@example.com"
    code = emailed_code(mail)

    res = client.post("/auth/reset-password", json={"code": code, "new_password": "after-reset"})
    assert res.status_code == 200
    assert login(client, "after-reset").status_code == 200
    assert login(client, "first-pass").status_code == 401
    # the code works only once
    again = client.post("/auth/reset-password", json={"code": code, "new_password": "another-one"})
    assert again.status_code == 400


def test_reset_falls_back_to_alert_address(client, mail, monkeypatch):
    monkeypatch.delenv("RESET_EMAIL_TO")
    monkeypatch.setenv("ALERT_EMAIL_TO", "alerts@example.com")
    assert client.post("/auth/forgot-password").status_code == 200
    assert mail.sent[0]["To"] == "alerts@example.com"


def test_forgot_password_without_email_setup(client):
    res = client.post("/auth/forgot-password")
    assert res.status_code == 503 and "not set up" in res.json()["detail"]


def test_forgot_password_mail_failure(client, mail):
    mail.fail_with = ConnectionRefusedError("refused")
    res = client.post("/auth/forgot-password")
    assert res.status_code == 502
    # no code was stored, so nothing can be reset
    assert client.post("/auth/reset-password", json={"code": "000000", "new_password": "after-reset"}).status_code == 400


def test_one_reset_email_per_minute(client, mail):
    assert client.post("/auth/forgot-password").status_code == 200
    assert client.post("/auth/forgot-password").status_code == 429
    assert len(mail.sent) == 1


def test_wrong_codes_cancel_the_code(client, mail):
    client.post("/auth/forgot-password")
    code = emailed_code(mail)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(auth.CODE_MAX_TRIES - 1):
        assert client.post("/auth/reset-password", json={"code": wrong, "new_password": "after-reset"}).json()["detail"] == "Wrong code."
    last = client.post("/auth/reset-password", json={"code": wrong, "new_password": "after-reset"})
    assert "Too many wrong codes" in last.json()["detail"]
    # even the right code no longer works
    assert client.post("/auth/reset-password", json={"code": code, "new_password": "after-reset"}).status_code == 400


def test_expired_code(client, mail):
    client.post("/auth/forgot-password")
    code = emailed_code(mail)
    db, row = db_row(client)
    row.reset_expires_at = datetime.now() - timedelta(seconds=1)
    db.commit()
    res = client.post("/auth/reset-password", json={"code": code, "new_password": "after-reset"})
    assert res.status_code == 400 and "Ask for a new one" in res.json()["detail"]
