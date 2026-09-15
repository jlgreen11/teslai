import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from teslai.api.app import create_app
from teslai.builder import Session
from teslai.db import repo

pytestmark = pytest.mark.integration


@pytest.fixture()
def client(engine):
    with engine.begin() as conn:
        tag = uuid.uuid4().hex
        a = repo.create_account(conn, f"owner-{tag}")
        v = repo.create_vehicle(conn, a, f"APIVIN{tag}"[:17].upper(), "Test car",
                                "America/Chicago")
        t0 = datetime(2026, 7, 1, 13, tzinfo=UTC)
        repo.replace_sessions(conn, a, v, t0 - timedelta(days=1), t0 + timedelta(days=2), [
            Session("sleep", t0 - timedelta(hours=10), t0),
            Session("drive", t0, t0 + timedelta(minutes=25), start_odometer=1000.0,
                    end_odometer=1012.0, start_battery=80, end_battery=77),
            Session("charge", t0 + timedelta(hours=1), t0 + timedelta(hours=3),
                    energy_added_kwh=15.5, charger="ac"),
            Session("idle", t0 + timedelta(hours=3)),
        ], "teslafi_import", 1)
    yield TestClient(create_app(engine=engine, account_id=a)), v


def test_health_and_vehicle_list_hide_full_vin(client):
    c, v = client
    assert c.get("/healthz").json()["ok"] is True
    [veh] = c.get("/api/v1/vehicles").json()
    assert veh["id"] == v and len(veh["vin_last4"]) == 4 and "vin" not in veh


def test_day_view_includes_overlapping_sleep_and_open_idle(client):
    c, v = client
    body = c.get(f"/api/v1/vehicles/{v}/days/2026-07-01").json()
    assert [s["kind"] for s in body["sessions"]] == ["sleep", "drive", "charge", "idle"]
    assert body["drives"] == 1 and body["miles"] == 12.0 and body["kwh_added"] == 15.5
    assert body["sessions"][-1]["end"] is None


def test_unknown_vehicle_is_404_and_bad_range_is_422(client):
    c, v = client
    assert c.get("/api/v1/vehicles/999999/days/2026-07-01").status_code == 404
    r = c.get(f"/api/v1/vehicles/{v}/sessions",
              params={"start": "2026-07-02T00:00:00+00:00", "end": "2026-07-01T00:00:00+00:00"})
    assert r.status_code == 422


def test_index_page_served(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200 and "teslai day" in r.text
