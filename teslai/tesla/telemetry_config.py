"""Build, diff, push and check the car's Fleet Telemetry config.

The config is pushed through Tesla's vehicle-command HTTP proxy, which signs it
with the app's private key:

    POST <proxy>/api/1/vehicles/fleet_telemetry_config
    {"vins": [...], "config": {"hostname", "port", "ca", "fields": {Name: {"interval_seconds",
     "minimum_delta"}}, "prefer_typed", "alert_types", "exp"}}

Status is read directly from the Fleet API:

    GET <fleet base>/api/1/vehicles/<vin>/fleet_telemetry_config
    {"response": {"synced": bool, "limit_reached": bool, "config": {...} | null, ...}}

`ca` must be the private CA certificate, never Caddy's public certificate.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from teslai.config import FieldSpec
from teslai.errors import TeslaiError
from teslai.tesla.auth import raise_for_tesla

SIGNAL_PRICE_USD = 0.0001
SKIP_REASON_CODES = {
    "missing_key": "TSL-KEY-UNPAIRED",
    "unsupported_firmware": "TSL-FIRMWARE-TOO-OLD",
    "unsupported_hardware": "TSL-HARDWARE-UNSUPPORTED",
    "max_configs": "TSL-CONFIG-NULL",
}


def desired_config(specs: dict[str, FieldSpec], hostname: str, port: int, ca_pem: str,
                   exp: datetime | None = None, alert_types: tuple[str, ...] = ("service",)) -> dict:
    fields: dict[str, dict] = {}
    for name, spec in sorted(specs.items()):
        entry: dict = {"interval_seconds": spec.interval_seconds}
        if spec.minimum_delta is not None:
            entry["minimum_delta"] = spec.minimum_delta
        fields[name] = entry
    config = {"hostname": hostname, "port": port, "ca": ca_pem, "fields": fields,
              "prefer_typed": True, "alert_types": list(alert_types)}
    if exp is not None:
        config["exp"] = int(exp.timestamp())
    return config


def request_body(vins: list[str], config: dict) -> dict:
    if not vins:
        raise TeslaiError("TSL-ENV-INCOMPLETE", "TESLA_VIN is empty")
    return {"vins": vins, "config": config}


@dataclass
class PushResult:
    updated_vehicles: int
    problems: list[tuple[str, str]] = field(default_factory=list)  # (vin, catalog code)


def push(http: httpx.Client, proxy_url: str, token: str, body: dict) -> PushResult:
    resp = http.post(f"{proxy_url}/api/1/vehicles/fleet_telemetry_config", json=body,
                     headers={"Authorization": f"Bearer {token}"})
    raise_for_tesla(resp, "telemetry config push")
    data = resp.json().get("response", {})
    result = PushResult(int(data.get("updated_vehicles", 0)))
    for reason, vins in (data.get("skipped_vehicles") or {}).items():
        code = SKIP_REASON_CODES.get(reason, "TSL-CONFIG-UNSYNCED")
        for vin in vins or []:
            result.problems.append((vin, code))
    return result


@dataclass
class RemoteStatus:
    synced: bool
    limit_reached: bool
    config: dict | None
    raw: dict


def fetch(http: httpx.Client, base_url: str, token: str, vin: str) -> RemoteStatus:
    resp = http.get(f"{base_url}/api/1/vehicles/{vin}/fleet_telemetry_config",
                    headers={"Authorization": f"Bearer {token}"})
    raise_for_tesla(resp, "telemetry config status")
    data = resp.json().get("response", {})
    return RemoteStatus(bool(data.get("synced")), bool(data.get("limit_reached")),
                        data.get("config"), data)


def diff(desired: dict, remote: dict | None) -> list[str]:
    if remote is None:
        return ["car has no teslai config"]
    changes = []
    for key in ("hostname", "port", "ca", "prefer_typed"):
        if desired.get(key) != remote.get(key):
            changes.append(f"{key} differs" if key == "ca" else
                           f"{key}: car has {remote.get(key)!r}, want {desired.get(key)!r}")
    want, have = desired.get("fields", {}), remote.get("fields", {}) or {}
    for name in sorted(set(want) - set(have)):
        changes.append(f"field {name}: missing on car")
    for name in sorted(set(have) - set(want)):
        changes.append(f"field {name}: on car but not in telemetry.yaml")
    for name in sorted(set(want) & set(have)):
        for k in ("interval_seconds", "minimum_delta"):
            if want[name].get(k) != have[name].get(k):
                changes.append(f"field {name}.{k}: car {have[name].get(k)}, want {want[name].get(k)}")
    return changes


def check_status(status: RemoteStatus, desired: dict,
                 now: datetime | None = None) -> list[str]:
    """Catalog codes for everything wrong with the car's current config."""
    now = now or datetime.now(UTC)
    codes = []
    if status.limit_reached or (status.synced and status.config is None):
        codes.append("TSL-CONFIG-NULL")
        return codes
    if not status.synced:
        codes.append("TSL-CONFIG-UNSYNCED")
    if status.config:
        if status.config.get("ca") != desired.get("ca"):
            codes.append("TSL-CA-MISMATCH")
        exp = status.config.get("exp")
        if exp and datetime.fromtimestamp(int(exp), UTC) - now < timedelta(days=14):
            codes.append("TSL-CONFIG-EXPIRING")
    return codes


def monthly_signal_upper_bound(specs: dict[str, FieldSpec], awake_hours_per_day: float) -> tuple[int, float]:
    """Signals and USD per 30 days if every field changed at its maximum allowed rate
    whenever the car is awake. Real usage is far lower because fields send only on change."""
    per_hour = sum(3600 / s.interval_seconds for s in specs.values())
    signals = int(per_hour * awake_hours_per_day * 30)
    return signals, round(signals * SIGNAL_PRICE_USD, 2)
