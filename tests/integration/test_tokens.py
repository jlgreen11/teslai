import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from teslai.db import repo
from teslai.errors import TeslaiError
from teslai.tesla.auth import TokenSet
from teslai.tesla.tokens import get_access_token, save_tokens

pytestmark = pytest.mark.integration


def _account(engine, name):
    with engine.begin() as conn:
        return repo.create_account(conn, name)


def test_tokens_encrypted_at_rest_and_valid_token_not_refreshed(engine):
    a = _account(engine, "tok-valid")
    cipher = Fernet(Fernet.generate_key())
    save_tokens(engine, cipher, a, "cid", "na", ["openid"],
                TokenSet("ACCESS-1", "REFRESH-1", datetime.now(UTC) + timedelta(hours=2)))
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT refresh_token_enc FROM tesla_connections WHERE account_id=:a"),
                           {"a": a}).scalar()
    assert b"REFRESH-1" not in bytes(raw)
    calls = []
    assert get_access_token(engine, cipher, a, lambda rt: calls.append(rt)) == "ACCESS-1"
    assert calls == []


def test_concurrent_callers_refresh_exactly_once(engine):
    a = _account(engine, "tok-race")
    cipher = Fernet(Fernet.generate_key())
    save_tokens(engine, cipher, a, "cid", "na", ["openid"],
                TokenSet("OLD", "R-OLD", datetime.now(UTC) - timedelta(minutes=1)))
    spent: list[str] = []

    def do_refresh(rt: str) -> TokenSet:
        spent.append(rt)
        time.sleep(0.3)  # widen the race window
        return TokenSet("NEW", "R-NEW", datetime.now(UTC) + timedelta(hours=8))

    results: list[str] = []
    threads = [threading.Thread(target=lambda: results.append(
        get_access_token(engine, cipher, a, do_refresh))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert spent == ["R-OLD"]
    assert results == ["NEW"] * 4
    with engine.connect() as conn:
        assert conn.execute(text("SELECT refresh_count FROM tesla_connections WHERE account_id=:a"),
                            {"a": a}).scalar() == 1


def test_missing_login_is_catalog_error(engine):
    a = _account(engine, "tok-none")
    with pytest.raises(TeslaiError) as exc:
        get_access_token(engine, Fernet(Fernet.generate_key()), a, lambda rt: None)
    assert exc.value.info.code == "TSL-TESLA-UNCONFIGURED"
