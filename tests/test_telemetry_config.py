import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from teslai.config import load_field_specs
from teslai.errors import CATALOG, TeslaiError
from teslai.tesla import regions
from teslai.tesla.telemetry_config import (
    RemoteStatus,
    check_status,
    desired_config,
    diff,
    fetch,
    monthly_signal_upper_bound,
    push,
    request_body,
)

NOW = datetime(2026, 9, 15, tzinfo=UTC)
CA = "-----BEGIN CERTIFICATE-----\nPRIVATE\n-----END CERTIFICATE-----\n"


def cfg(**kw):
    return desired_config(load_field_specs(), "telemetry.cars.example.org", 4443, CA,
                          exp=NOW + timedelta(days=365), **kw)


def test_desired_config_from_shipped_specs():
    c = cfg()
    assert c["hostname"] == "telemetry.cars.example.org" and c["port"] == 4443 and c["ca"] == CA
    assert c["prefer_typed"] is True and c["exp"] == int((NOW + timedelta(days=365)).timestamp())
    assert "RouteLine" not in c["fields"]
    assert c["fields"]["Gear"] == {"interval_seconds": 1}
    assert c["fields"]["BatteryLevel"] == {"interval_seconds": 60, "minimum_delta": 0.5}


def test_request_body_requires_vin():
    with pytest.raises(TeslaiError):
        request_body([], cfg())
    assert request_body(["5YJYGDEE1LF000001"], cfg())["vins"] == ["5YJYGDEE1LF000001"]


def test_push_goes_to_proxy_and_maps_skipped_vehicles():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"response": {"updated_vehicles": 0, "skipped_vehicles": {
            "missing_key": ["VINA"], "unsupported_firmware": ["VINB"], "new_reason": ["VINC"]}}})

    r = push(httpx.Client(transport=httpx.MockTransport(handler)), "https://proxy:4443", "tok",
             request_body(["VINA"], cfg()))
    assert seen["url"] == "https://proxy:4443/api/1/vehicles/fleet_telemetry_config"
    assert seen["body"]["config"]["ca"] == CA
    assert r.problems == [("VINA", "TSL-KEY-UNPAIRED"), ("VINB", "TSL-FIRMWARE-TOO-OLD"),
                          ("VINC", "TSL-CONFIG-UNSYNCED")]
    assert all(code in CATALOG for _, code in r.problems)


def test_fetch_and_status_codes():
    body = {"response": {"synced": False, "limit_reached": False,
                         "config": {**cfg(), "ca": "OTHER", "exp": int((NOW + timedelta(days=3)).timestamp())}}}
    st = fetch(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))),
               "https://fleet", "tok", "VIN")
    assert check_status(st, cfg(), now=NOW) == ["TSL-CONFIG-UNSYNCED", "TSL-CA-MISMATCH",
                                                "TSL-CONFIG-EXPIRING"]
    assert check_status(RemoteStatus(True, False, None, {}), cfg()) == ["TSL-CONFIG-NULL"]
    assert check_status(RemoteStatus(False, True, cfg(), {}), cfg()) == ["TSL-CONFIG-NULL"]
    assert check_status(RemoteStatus(True, False, cfg(), {}), cfg(), now=NOW) == []


def test_diff_reports_field_and_connection_changes():
    want = cfg()
    have = json.loads(json.dumps(want))
    have["fields"]["Gear"]["interval_seconds"] = 5
    del have["fields"]["Locked"]
    have["fields"]["RouteLine"] = {"interval_seconds": 1}
    have["hostname"] = "old.example.org"
    have["ca"] = "OTHER"
    changes = diff(want, have)
    assert "field Gear.interval_seconds: car 5, want 1" in changes
    assert "field Locked: missing on car" in changes
    assert "field RouteLine: on car but not in telemetry.yaml" in changes
    assert "ca differs" in changes and any(c.startswith("hostname") for c in changes)
    assert diff(want, None) == ["car has no teslai config"]
    assert diff(want, json.loads(json.dumps(want))) == []


def test_upper_bound_scales_with_awake_hours():
    specs = load_field_specs()
    s3, usd3 = monthly_signal_upper_bound(specs, 3)
    s6, _ = monthly_signal_upper_bound(specs, 6)
    assert s6 == pytest.approx(2 * s3, rel=0.001) and usd3 > 0


def test_region_base_urls():
    assert regions.base_url("na") == "https://fleet-api.prd.na.vn.cloud.tesla.com"
    assert regions.base_url("EU").endswith(".eu.vn.cloud.tesla.com")
    with pytest.raises(TeslaiError) as exc:
        regions.base_url("mars")
    assert exc.value.info.code == "TSL-REGION-WRONG"
