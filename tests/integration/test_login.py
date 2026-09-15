import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text

from teslai import owner_auth
from teslai.api.app import create_app
from teslai.db import repo

pytestmark = pytest.mark.integration
SECRET = "s" * 40


@pytest.fixture()
def setup(engine):
    cipher = Fernet(Fernet.generate_key())
    email = f"owner-{uuid.uuid4().hex[:8]}@example.org"
    totp_secret = owner_auth.new_totp_secret()
    with engine.begin() as conn:
        a = repo.create_account(conn, email)
        conn.execute(text("INSERT INTO users (account_id, email, password_hash, totp_secret_enc) "
                          "VALUES (:a, :e, :p, :t)"),
                     {"a": a, "e": email, "p": owner_auth.hash_password("correct horse battery"),
                      "t": cipher.encrypt(totp_secret.encode())})
    app = create_app(engine=engine, account_id=a, session_secret=SECRET, cipher=cipher,
                     secure_cookies=False)
    return TestClient(app), email, totp_secret


def test_api_requires_login_and_pages_redirect(setup):
    c, _, _ = setup
    assert c.get("/healthz").status_code == 200
    assert c.get("/api/v1/vehicles").status_code == 401
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/login").status_code == 200


def test_login_with_password_and_code_sets_cookie(setup):
    c, email, totp_secret = setup
    r = c.post("/api/v1/login", json={"email": email, "password": "correct horse battery",
                                       "code": owner_auth.totp(totp_secret)})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/api/v1/vehicles").status_code == 200


def test_wrong_code_is_rejected_generically_and_locks_after_five(setup):
    c, email, totp_secret = setup
    bad = {"email": email, "password": "correct horse battery", "code": "000000"}
    for _ in range(5):
        r = c.post("/api/v1/login", json=bad)
        assert r.status_code == 401 and "incorrect" in r.json()["detail"]
    good = {**bad, "code": owner_auth.totp(totp_secret)}
    assert c.post("/api/v1/login", json=good).status_code == 429


def test_unknown_email_gets_same_message(setup):
    c, _, _ = setup
    r = c.post("/api/v1/login", json={"email": "nobody@example.org", "password": "x" * 12,
                                       "code": "123456"})
    assert r.status_code == 401 and "incorrect" in r.json()["detail"]


def test_new_pages_require_login_and_assets_are_public(setup):
    c, email, totp_secret = setup
    for path in ("/months", "/battery"):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/static/app.css").status_code == 200
    c.post("/api/v1/login", json={"email": email, "password": "correct horse battery",
                                  "code": owner_auth.totp(totp_secret)})
    assert "teslai battery" in c.get("/battery").text and "teslai months" in c.get("/months").text
