"""Owner login: password plus TOTP, signed session cookies, lockout.

    POST /api/v1/login {email, password, code}
        ├─ account locked?            -> 429, no password check
        ├─ scrypt(password) matches?  ─┐
        ├─ TOTP code valid (±1 step)? ─┴─ both yes -> Set-Cookie teslai_session (HttpOnly,
        │                                             Secure, SameSite=Strict), reset counter
        └─ otherwise                  -> 401 generic message, counter += 1,
                                         5 failures lock the account for 15 minutes

The session cookie is base64(json{uid, exp}) + "." + HMAC-SHA256 with
TESLAI_SESSION_SECRET. No server-side session table is needed for one owner.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
SESSION_COOKIE = "teslai_session"
SESSION_TTL = timedelta(days=14)
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=15)


def hash_password(password: str, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n),
                                   r=int(r), p=int(p), dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % 10**digits
    return str(code).zfill(digits)


def verify_totp(secret: str, code: str, at: float | None = None, window: int = 1) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit():
        return False
    now = time.time() if at is None else at
    return any(hmac.compare_digest(totp(secret, now + i * 30), code)
               for i in range(-window, window + 1))


def provisioning_uri(secret: str, email: str, issuer: str = "teslai") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30")


def sign_session(user_id: int, secret: str, now: datetime | None = None) -> str:
    exp = int(((now or datetime.now(UTC)) + SESSION_TTL).timestamp())
    body = base64.urlsafe_b64encode(json.dumps({"uid": user_id, "exp": exp}).encode()).decode()
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def read_session(cookie: str | None, secret: str, now: datetime | None = None) -> int | None:
    if not cookie or "." not in cookie or not secret:
        return None
    body, mac = cookie.rsplit(".", 1)
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body.encode()))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(data.get("exp", 0)) < (now or datetime.now(UTC)).timestamp():
        return None
    return int(data["uid"])
