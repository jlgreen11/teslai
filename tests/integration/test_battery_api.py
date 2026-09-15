import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from teslai.api.app import create_app
from teslai.builder import Session
from teslai.db import repo

pytestmark = pytest.mark.integration


def test_battery_endpoint_reports_loss(engine):
    tag = uuid.uuid4().hex[:10].upper()
    t0 = datetime(2025, 3, 1, 23, tzinfo=UTC)
    with engine.begin() as conn:
        a = repo.create_account(conn, f"batt-{tag}")
        v = repo.create_vehicle(conn, a, f"BAT{tag}0000"[:17], "Car", "America/Chicago")
        sessions = [Session("charge", t0 + timedelta(days=d), t0 + timedelta(days=d, hours=2),
                            energy_added_kwh=20, charger="ac", end_battery=90,
                            end_rated_range=300 - (0 if d < 200 else 15))
                    for d in range(0, 400, 20)]
        repo.replace_sessions(conn, a, v, t0 - timedelta(days=1), t0 + timedelta(days=500),
                              sessions, "teslafi_import", 1)
    c = TestClient(create_app(engine=engine, account_id=a, require_login=False))
    body = c.get(f"/api/v1/vehicles/{v}/battery").json()
    assert body["baseline"] == 333.3 and body["current"] == 316.7
    assert body["loss_pct"] == 5.0 and len(body["points"]) == 20
