import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from teslai import demo
from teslai.api.app import create_app
from teslai.db import repo

pytestmark = pytest.mark.integration
END = date(2026, 6, 14)


@pytest.fixture(scope="module")
def client(engine):
    with engine.begin() as conn:
        tag = uuid.uuid4().hex[:8].upper()
        a = repo.create_account(conn, f"views-{tag}")
        v = repo.create_vehicle(conn, a, f"VIEWS{tag}0000"[:17], "Demo", "America/Chicago")
        demo.seed(conn, a, v, days=21, end=END)
    return TestClient(create_app(engine=engine, account_id=a, require_login=False)), v


def test_status_reports_latest_state(client):
    c, v = client
    s = c.get(f"/api/v1/vehicles/{v}/status").json()
    assert s["name"] == "Demo" and s["state"] in {"asleep", "offline"}
    assert 0 < s["battery_level"] <= 100 and s["est_100_range"] > 250 and s["version"]
    assert s["tpms"]["fl"] > 2 and s["locked"] is not None and s["charge_limit"] == 80


def test_session_list_detail_and_navigation(client):
    c, v = client
    page = c.get(f"/api/v1/vehicles/{v}/session-list", params={"kind": "drive", "start": "2026-05-25", "end": "2026-06-14"}).json()
    assert page["total"] > 20 and page["totals"]["miles"] > 100 and page["totals"]["wh_per_mile"] > 150
    newest = page["items"][0]
    assert newest["start"] >= page["items"][-1]["start"] and newest["wh_per_mile"]
    d = c.get(f"/api/v1/vehicles/{v}/session/{newest['id']}").json()
    assert d["session"]["id"] == newest["id"] and d["next_id"] is None and d["prev_id"]
    assert len(d["samples"]) > 5 and any(p["lat"] for p in d["samples"]) and any(p["speed"] for p in d["samples"])
    assert c.get(f"/api/v1/vehicles/{v}/session/999999999").status_code == 404
    assert c.get(f"/api/v1/vehicles/{v}/session-list", params={"kind": "bogus"}).status_code == 422
    parked = c.get(f"/api/v1/vehicles/{v}/session-list", params={"kind": "idle,sleep", "end": "2026-06-14"}).json()
    assert {s["kind"] for s in parked["items"]} <= {"idle", "sleep"} and parked["total"] > 0


def test_timeline_calendar_and_analytics(client):
    c, v = client
    t = c.get(f"/api/v1/vehicles/{v}/timeline/2026-06-10").json()
    assert len(t["week"]) == 7 and len(t["battery"]) > 10 and t["totals"]["drives"] == t["drives"]
    m = c.get(f"/api/v1/vehicles/{v}/calendar/2026/6").json()
    assert len(m["days"]) == 30 and m["summary"]["days_driven"] >= 10
    y = c.get(f"/api/v1/vehicles/{v}/calendar/2026").json()
    assert [x["month"] for x in y["months"]] == ["2026-05", "2026-06"]
    e = c.get(f"/api/v1/vehicles/{v}/efficiency", params={"end": "2026-06-14"}).json()
    assert e["temperature"] and e["speed"]
    locs = c.get(f"/api/v1/vehicles/{v}/charge-locations", params={"end": "2026-06-14"}).json()["locations"]
    assert "Home" in {x["location"] for x in locs}
    tires = c.get(f"/api/v1/vehicles/{v}/tires", params={"end": "2026-06-14"}).json()["days"]
    assert len(tires) >= 20 and tires[0]["fl"] > 2
    mp = c.get(f"/api/v1/vehicles/{v}/map", params={"end": "2026-06-14"}).json()
    assert len(mp["tracks"]) > 20 and len(mp["places"]) >= 6


def test_unknown_api_path_is_404_not_web_app(client):
    c, _ = client
    assert c.get("/api/v1/nope").status_code == 404
    assert c.get("/drives/123").status_code in (200, 503)
