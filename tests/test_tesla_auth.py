from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from teslai.errors import TeslaiError
from teslai.tesla import auth

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
BASE = "https://fleet.example.test"


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_authorize_url_has_required_params_and_offline_access():
    url = auth.authorize_url("cid", "https://cars.example.org/callback", "st8")
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://auth.tesla.com/oauth2/v3/authorize?")
    assert q["response_type"] == ["code"] and q["state"] == ["st8"]
    assert "offline_access" in q["scope"][0].split() and "openid" in q["scope"][0].split()


def test_code_exchange_posts_form_and_returns_tokens():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["form"] = parse_qs(req.content.decode())
        return httpx.Response(200, json={"access_token": "A1", "refresh_token": "R1",
                                         "expires_in": 3600})

    t = auth.exchange_code(client(handler), "cid", "sec", "CODE", "https://x/cb", BASE, now=NOW)
    assert seen["url"] == auth.TOKEN_URL
    assert seen["form"]["grant_type"] == ["authorization_code"]
    assert seen["form"]["audience"] == [BASE]
    assert (t.access_token, t.refresh_token, t.expires_at) == ("A1", "R1", NOW + timedelta(hours=1))


def test_refresh_invalid_grant_maps_to_token_consumed():
    def handler(req):
        return httpx.Response(401, json={"error": "invalid_grant"})

    with pytest.raises(TeslaiError) as exc:
        auth.refresh(client(handler), "cid", "old")
    assert exc.value.info.code == "TSL-TOKEN-CONSUMED"


@pytest.mark.parametrize("status,code", [(402, "TSL-BILLING-DISABLED"), (403, "TSL-SCOPE-MISSING"),
                                         (412, "TSL-PARTNER-UNREGISTERED"), (421, "TSL-REGION-WRONG")])
def test_status_codes_map_to_catalog(status, code):
    with pytest.raises(TeslaiError) as exc:
        auth.register_partner(client(lambda r: httpx.Response(status, text="nope")), BASE, "t",
                              "cars.example.org")
    assert exc.value.info.code == code


def test_register_sends_domain_with_bearer_token():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        seen["body"] = req.content
        return httpx.Response(200, json={"response": {"domain": "cars.example.org"}})

    auth.register_partner(client(handler), BASE, "PT", "cars.example.org")
    assert seen["auth"] == "Bearer PT" and b'"domain"' in seen["body"]


def test_public_key_match_accepts_hex_point_and_pem():
    key = ec.generate_private_key(ec.SECP256R1()).public_key()
    pem = key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    point = key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    assert auth.public_key_matches(point.hex(), pem)
    assert auth.public_key_matches(pem.decode(), pem)
    other = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    assert not auth.public_key_matches(other.hex(), pem)
    assert not auth.public_key_matches("zz-not-hex", pem)
