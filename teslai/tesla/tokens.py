"""Encrypted Tesla token storage with a single refresher.

    get_access_token()
        BEGIN
        SELECT ... FROM tesla_connections WHERE account_id = :a FOR UPDATE   <- serializes refreshers
        access token still valid for 5+ minutes?  -> return it
        else refresh with Tesla, UPDATE both tokens in the same transaction
        COMMIT

A second process asking at the same moment waits on the row lock, then sees the
fresh token and does not refresh again, so a single-use refresh token is never
spent twice.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import Engine, text

from teslai.errors import TeslaiError
from teslai.tesla.auth import TokenSet

REFRESH_MARGIN = timedelta(minutes=5)


def load_or_create_cipher(path: Path) -> Fernet:
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        path.chmod(0o600)
    return Fernet(path.read_bytes())


def save_tokens(engine: Engine, cipher: Fernet, account_id: int, client_id: str, region: str,
                scopes: list[str], tokens: TokenSet) -> None:
    if not tokens.refresh_token:
        raise TeslaiError("TSL-TOKEN-CONSUMED", "login returned no refresh token")
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO tesla_connections (account_id, client_id, region, scopes,
                access_token_enc, refresh_token_enc, access_expires_at, updated_at)
            VALUES (:a, :c, :r, :s, :at, :rt, :exp, now())
            ON CONFLICT (account_id) DO UPDATE SET client_id = EXCLUDED.client_id,
                region = EXCLUDED.region, scopes = EXCLUDED.scopes,
                access_token_enc = EXCLUDED.access_token_enc,
                refresh_token_enc = EXCLUDED.refresh_token_enc,
                access_expires_at = EXCLUDED.access_expires_at, updated_at = now()"""),
            {"a": account_id, "c": client_id, "r": region, "s": scopes,
             "at": cipher.encrypt(tokens.access_token.encode()),
             "rt": cipher.encrypt(tokens.refresh_token.encode()), "exp": tokens.expires_at})


def get_access_token(engine: Engine, cipher: Fernet, account_id: int,
                     do_refresh: Callable[[str], TokenSet],
                     now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> str:
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT access_token_enc, refresh_token_enc, access_expires_at "
            "FROM tesla_connections WHERE account_id = :a FOR UPDATE"), {"a": account_id}).first()
        if row is None:
            raise TeslaiError("TSL-TESLA-UNCONFIGURED", "no Tesla login stored; run teslai tesla login")
        if row.access_expires_at - now() > REFRESH_MARGIN:
            return cipher.decrypt(bytes(row.access_token_enc)).decode()
        tokens = do_refresh(cipher.decrypt(bytes(row.refresh_token_enc)).decode())
        conn.execute(text(
            "UPDATE tesla_connections SET access_token_enc = :at, refresh_token_enc = :rt, "
            "access_expires_at = :exp, refresh_count = refresh_count + 1, updated_at = now() "
            "WHERE account_id = :a"),
            {"a": account_id, "at": cipher.encrypt(tokens.access_token.encode()),
             "rt": cipher.encrypt(tokens.refresh_token.encode()),  # type: ignore[union-attr]
             "exp": tokens.expires_at})
        return tokens.access_token


def token_age(engine: Engine, account_id: int) -> timedelta | None:
    with engine.connect() as conn:
        updated = conn.execute(text("SELECT updated_at FROM tesla_connections WHERE account_id=:a"),
                               {"a": account_id}).scalar()
    return None if updated is None else datetime.now(UTC) - updated
