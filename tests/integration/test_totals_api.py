import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from teslai.api.app import create_app
from teslai.builder import Session
from teslai.db import repo

pytestmark = pytest.mark.integration


def test_totals_and_csv_export(engine):
    tag = uuid.uuid4().hex[:10].upper()
    t0 = datetime(2026, 6, 10, 14, tzinfo=UTC)
    with engine.begin() as conn:
        a = repo.create_account(conn, f"totals-{tag}")
        v = repo.create_vehicle(conn, a, f"TOT{tag}0000"[:17], "Car", "America/Chicago")
        repo.replace_sessions(conn, a, v, t0 - timedelta(days=1), t0 + timedelta(days=60), [
            Session("drive", t0, t0 + timedelta(minutes=30), start_odometer=100.0, end_odometer=112.0),
            Session("charge", t0 + timedelta(hours=6), t0 + timedelta(hours=8), energy_added_kwh=9.0, charger="ac"),
            Session("drive", t0 + timedelta(days=30), t0 + timedelta(days=30, minutes=15),
                    start_odometer=112.0, end_odometer=120.0),
        ], "teslafi_import", 1)
    c = TestClient(create_app(engine=engine, account_id=a, require_login=False))
    t = c.get(f"/api/v1/vehicles/{v}/totals", params={"start": "2026-06-01", "end": "2026-07-31"}).json()
    assert [(x["period"], x["drives"], x["miles"], x["charges"]) for x in t] == \
        [("2026-06", 1, 12.0, 1), ("2026-07", 1, 8.0, 0)]
    r = c.get(f"/api/v1/vehicles/{v}/sessions.csv",
              params={"start": "2026-06-01", "end": "2026-06-30", "kind": "drive"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="teslai-drive-2026-06-01-2026-06-30.csv"' in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 1 and rows[0]["distance_miles"] == "12.0"
    assert c.get(f"/api/v1/vehicles/{v}/totals",
                 params={"start": "2026-07-01", "end": "2026-06-01"}).status_code == 422
    assert c.get(f"/api/v1/vehicles/{v}/totals",
                 params={"start": "2026-06-01", "end": "2026-06-30", "group": "week"}).status_code == 422
    assert c.get(f"/api/v1/vehicles/{v}/sessions.csv",
                 params={"start": "2026-06-01", "end": "2026-06-30", "kind": "nap"}).status_code == 422
