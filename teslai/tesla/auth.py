"""Tesla OAuth, partner registration and error mapping.

Owner login (third-party token flow):
    1. Browser to https://auth.tesla.com/oauth2/v3/authorize?response_type=code&...
    2. Tesla redirects to redirect_uri with ?code=...&state=...
    3. POST https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token
       grant_type=authorization_code, client_id, client_secret, code, audience, redirect_uri
Refresh:
    POST the same token URL with grant_type=refresh_token, client_id, refresh_token.
    Refresh tokens are single use and expire after 3 months; always store the new one.
    teslai.tesla.tokens holds a row lock so only one process refreshes at a time.

Partner registration (once per region, with a client_credentials partner token):
    POST <fleet base>/api/1/partner_accounts {"domain": ...}
    Tesla fetches https://<domain>/.well-known/appspecific/com.tesla.3p.public-key.pem
    GET  <fleet base>/api/1/partner_accounts/public_key?domain=... confirms it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from teslai.errors import TeslaiError

AUTHORIZE_URL = "https://auth.tesla.com/oauth2/v3/authorize"
TOKEN_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"

# Minimal scopes for logging. offline_access is required for a refresh token.
# vehicle_location is needed for the Location telemetry field; verify the scope
# name against developer.tesla.com if login reports it as unknown.
LOGGING_SCOPES = ["openid", "offline_access", "user_data", "vehicle_device_data",
                  "vehicle_location"]
PARTNER_SCOPES = ["openid", "vehicle_device_data"]

STATUS_CODES = {
    402: "TSL-BILLING-DISABLED",
    403: "TSL-SCOPE-MISSING",
    412: "TSL-PARTNER-UNREGISTERED",
    421: "TSL-REGION-WRONG",
}


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime


def raise_for_tesla(resp: httpx.Response, context: str) -> None:
    """Map Tesla error responses to catalog errors, keeping the response body as detail."""
    if resp.is_success:
        return
    body = resp.text[:300]
    if resp.status_code in (400, 401) and "invalid_grant" in body:
        raise TeslaiError("TSL-TOKEN-CONSUMED", f"{context}: {body}")
    code = STATUS_CODES.get(resp.status_code)
    if code:
        raise TeslaiError(code, f"{context}: HTTP {resp.status_code} {body}")
    resp.raise_for_status()


def authorize_url(client_id: str, redirect_uri: str, state: str,
                  scopes: list[str] | None = None) -> str:
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
              "scope": " ".join(scopes or LOGGING_SCOPES), "state": state,
              "prompt_missing_scopes": "true"}
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _token_set(payload: dict, now: datetime) -> TokenSet:
    return TokenSet(access_token=payload["access_token"],
                    refresh_token=payload.get("refresh_token"),
                    expires_at=now + timedelta(seconds=int(payload.get("expires_in", 28800))))


def exchange_code(http: httpx.Client, client_id: str, client_secret: str, code: str,
                  redirect_uri: str, audience: str, now: datetime | None = None) -> TokenSet:
    resp = http.post(TOKEN_URL, data={
        "grant_type": "authorization_code", "client_id": client_id,
        "client_secret": client_secret, "code": code, "audience": audience,
        "redirect_uri": redirect_uri})
    raise_for_tesla(resp, "code exchange")
    return _token_set(resp.json(), now or datetime.now(UTC))


def refresh(http: httpx.Client, client_id: str, refresh_token: str,
            now: datetime | None = None) -> TokenSet:
    resp = http.post(TOKEN_URL, data={"grant_type": "refresh_token", "client_id": client_id,
                                      "refresh_token": refresh_token})
    raise_for_tesla(resp, "token refresh")
    tokens = _token_set(resp.json(), now or datetime.now(UTC))
    if not tokens.refresh_token:
        raise TeslaiError("TSL-TOKEN-CONSUMED", "refresh response had no new refresh token")
    return tokens


def partner_token(http: httpx.Client, client_id: str, client_secret: str, audience: str,
                  scopes: list[str] | None = None) -> str:
    resp = http.post(TOKEN_URL, data={
        "grant_type": "client_credentials", "client_id": client_id,
        "client_secret": client_secret, "audience": audience,
        "scope": " ".join(scopes or PARTNER_SCOPES)})
    raise_for_tesla(resp, "partner token")
    return resp.json()["access_token"]


def register_partner(http: httpx.Client, base_url: str, token: str, domain: str) -> dict:
    resp = http.post(f"{base_url}/api/1/partner_accounts", json={"domain": domain},
                     headers={"Authorization": f"Bearer {token}"})
    raise_for_tesla(resp, "partner registration")
    return resp.json()


def registered_public_key(http: httpx.Client, base_url: str, token: str, domain: str) -> str:
    resp = http.get(f"{base_url}/api/1/partner_accounts/public_key", params={"domain": domain},
                    headers={"Authorization": f"Bearer {token}"})
    raise_for_tesla(resp, "public key lookup")
    return resp.json().get("response", {}).get("public_key", "")


def public_key_matches(registered_hex_or_pem: str, local_pem: bytes) -> bool:
    """Compare Tesla's registered key (hex-encoded point or PEM) with the local public key."""
    from cryptography.hazmat.primitives import serialization

    local = serialization.load_pem_public_key(local_pem)
    local_point = local.public_bytes(serialization.Encoding.X962,
                                     serialization.PublicFormat.UncompressedPoint)
    value = registered_hex_or_pem.strip()
    if value.startswith("-----BEGIN"):
        remote = serialization.load_pem_public_key(value.encode())
        return remote.public_bytes(serialization.Encoding.X962,
                                   serialization.PublicFormat.UncompressedPoint) == local_point
    try:
        return bytes.fromhex(value) == local_point
    except ValueError:
        return False
