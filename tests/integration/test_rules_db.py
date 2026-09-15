import uuid
from datetime import UTC, datetime, timedelta

import pytest

from teslai import alerts
from teslai.db import repo
from teslai.places import Place
from teslai.reducer import Event
from teslai.rules import RuleConfig

pytestmark = pytest.mark.integration


def test_monitor_fires_car_alerts_from_stored_telemetry(engine):
    vin = ("RULES" + uuid.uuid4().hex.upper())[:17].replace("I", "1").replace("O", "0").replace("Q", "9")
    now = datetime.now(UTC)
    with engine.begin() as conn:
        a = repo.create_account(conn, f"rules-{vin}")
        v = repo.create_vehicle(conn, a, vin)
        repo.upsert_places(conn, a, [Place("Home", "home", 39.0, -94.5, 80)])
        repo.record_connectivity(conn, a, v, now - timedelta(hours=2), False)
        repo.insert_events(conn, a, [
            Event(v, now - timedelta(hours=3), "Gear", "ShiftStateP"),
            Event(v, now - timedelta(hours=3), "Location", {"latitude": 39.3, "longitude": -94.9}),
            Event(v, now - timedelta(hours=3), "Locked", False),
            Event(v, now - timedelta(hours=3), "TpmsPressureRl", 2.1),
            Event(v, now - timedelta(hours=3), "Version", "2026.30.1"),
        ])
    sent = []
    r = alerts.run_once(engine, a, lambda t, b: sent.append(t), now=now, rule_config=RuleConfig())
    assert sorted(c.code for c in r["fired"]) == ["TSL-CAR-UNLOCKED", "TSL-NEW-SOFTWARE", "TSL-TIRE-PRESSURE"]
    assert len(sent) == 3
    with engine.begin() as conn:
        repo.insert_events(conn, a, [Event(v, now + timedelta(minutes=1), "Version", "2026.32.0")])
    r2 = alerts.run_once(engine, a, lambda t, b: sent.append(t), now=now + timedelta(minutes=2),
                         rule_config=RuleConfig())
    assert [c.code for c in r2["fired"]] == ["TSL-NEW-SOFTWARE"]
    assert r2["resolved"] == []  # the old version's firing closes silently
