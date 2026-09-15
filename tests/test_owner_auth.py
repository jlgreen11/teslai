import time
from datetime import UTC, datetime, timedelta

import pytest

from teslai import owner_auth as oa


def test_rfc6238_sha1_test_vectors():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32("12345678901234567890")
    for t, code in [(59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924"),
                    (2000000000, "69279037")]:
        assert oa.totp(secret, at=t, digits=8) == code


def test_verify_totp_accepts_adjacent_step_only():
    s = oa.new_totp_secret()
    now = time.time()
    assert oa.verify_totp(s, oa.totp(s, now), at=now)
    assert oa.verify_totp(s, oa.totp(s, now - 30), at=now)
    assert not oa.verify_totp(s, oa.totp(s, now - 120), at=now)
    assert not oa.verify_totp(s, "abc123", at=now)


def test_password_hash_roundtrip_and_minimum_length():
    h = oa.hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert oa.verify_password("correct horse battery", h)
    assert not oa.verify_password("wrong horse battery", h)
    assert not oa.verify_password("x", "garbage")
    with pytest.raises(ValueError):
        oa.hash_password("short")


def test_session_signature_expiry_and_tamper():
    now = datetime(2026, 9, 15, tzinfo=UTC)
    c = oa.sign_session(7, "k" * 32, now=now)
    assert oa.read_session(c, "k" * 32, now=now) == 7
    assert oa.read_session(c, "other-secret", now=now) is None
    assert oa.read_session(c, "k" * 32, now=now + oa.SESSION_TTL + timedelta(seconds=1)) is None
    body, mac = c.rsplit(".", 1)
    assert oa.read_session(body.replace("A", "B", 1) + "." + mac, "k" * 32, now=now) is None
    assert oa.read_session(None, "k" * 32) is None


def test_provisioning_uri_format():
    uri = oa.provisioning_uri("ABC", "me@example.org")
    assert uri.startswith("otpauth://totp/teslai:me%40example.org?secret=ABC")
