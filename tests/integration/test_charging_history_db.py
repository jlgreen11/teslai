import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from teslai.api.app import create_app
from teslai.builder import Session
from teslai.db import repo
from teslai.tesla.charging_history import parse_record

pytestmark = pytest.mark.integration


def test_history_links_to_charge_and_invoice_overrides_cost(engine):
    tag = uuid.uuid4().hex[:10].upper()
    start = datetime(2026, 7, 1, 23, 2, tzinfo=UTC)
    with engine.begin() as conn:
        a = repo.create_account(conn, f"sc-{tag}")
        v = repo.create_vehicle(conn, a, f"SCH{tag}0000"[:17], "Car", "America/Chicago")
        repo.replace_sessions(conn, a, v, start - timedelta(days=1), start + timedelta(days=1), [
            Session("charge", start, start + timedelta(minutes=33), energy_added_kwh=40.0, charger="dc")],
            "teslafi_import", 1)
        rec = parse_record({"sessionId": "abc", "siteLocationName": "Belton, MO",
                            "chargeStartDateTime": "2026-07-01T18:00:00-05:00",
                            "chargeStopDateTime": "2026-07-01T18:35:00-05:00",
                            "fees": [{"currencyCode": "USD", "totalDue": 0}],
                            "invoices": [{"contentId": "c-9"}]})
        assert repo.store_charging_history(conn, a, v, [rec]) == {"stored": 1, "matched": 1}
        assert repo.store_charging_history(conn, a, v, [rec]) == {"stored": 1, "matched": 1}
    c = TestClient(create_app(engine=engine, account_id=a, require_login=False))
    day = c.get(f"/api/v1/vehicles/{v}/days/2026-07-01").json()
    [charge] = [s for s in day["sessions"] if s["kind"] == "charge"]
    assert charge["cost"] == 0.0 and charge["cost_source"] == "invoice"
    assert charge["end_place"] == "Belton, MO"
