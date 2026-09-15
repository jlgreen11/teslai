import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from teslai.api.app import create_app
from teslai.builder import Session
from teslai.db import repo
from teslai.places import Place

pytestmark = pytest.mark.integration
T0 = datetime(2026, 7, 1, 13, tzinfo=UTC)
HOME = {"latitude": 39.0, "longitude": -94.5}
AWAY = {"latitude": 39.3, "longitude": -94.9}


def test_sessions_tagged_retagged_and_priced_in_day_view(engine):
    tag = uuid.uuid4().hex[:10].upper()
    with engine.begin() as conn:
        a = repo.create_account(conn, f"places-{tag}")
        v = repo.create_vehicle(conn, a, f"PLC{tag}0000"[:17], "Car", "America/Chicago")
        repo.upsert_places(conn, a, [Place("Home", "home", 39.0, -94.5, 80)])
        places = repo.list_places(conn, a)
        sessions = [
            Session("drive", T0, T0 + timedelta(minutes=30), start_odometer=1000.0, end_odometer=1020.0,
                    start_location=HOME, end_location=AWAY),
            Session("charge", T0 + timedelta(hours=5), T0 + timedelta(hours=7), energy_added_kwh=14.0,
                    charger="ac", start_location=HOME, end_location=HOME),
        ]
        assert repo.replace_sessions(conn, a, v, T0 - timedelta(days=1), T0 + timedelta(days=1),
                                     sessions, "teslafi_import", 1, places=places) == 2
        repo.upsert_places(conn, a, [Place("Lake house", "free", 39.3, -94.9, 200)])
        assert repo.retag_sessions(conn, a) == 1
    client = TestClient(create_app(engine=engine, account_id=a, require_login=False))
    day = client.get(f"/api/v1/vehicles/{v}/days/{date(2026, 7, 1)}").json()
    drive, charge = day["sessions"]
    assert (drive["start_place"], drive["end_place"]) == ("Home", "Lake house")
    assert charge["end_place"] == "Home" and charge["cost"] is not None and charge["cost"] > 0
    assert day["charging_cost"] == charge["cost"]
