import uuid
from datetime import UTC, datetime, timedelta

import pytest

from teslai import alerts
from teslai.builder import Session
from teslai.db import repo
from teslai.rules import RuleConfig

pytestmark = pytest.mark.integration


def test_summaries_sent_once_for_recent_live_sessions_only(engine):
    tag = uuid.uuid4().hex[:10].upper()
    now = datetime.now(UTC).replace(microsecond=0)
    with engine.begin() as conn:
        a = repo.create_account(conn, f"summ-{tag}")
        v = repo.create_vehicle(conn, a, f"SUM{tag}0000"[:17], "Car", "America/Chicago")
        recent = now - timedelta(hours=2)
        repo.replace_sessions(conn, a, v, now - timedelta(days=30), now + timedelta(hours=1), [
            Session("drive", recent, recent + timedelta(minutes=25), start_odometer=10.0, end_odometer=22.0),
            Session("charge", recent + timedelta(hours=1), recent + timedelta(hours=1, minutes=40),
                    energy_added_kwh=5.0, charger="ac"),
            Session("drive", now - timedelta(days=3), now - timedelta(days=3) + timedelta(minutes=10),
                    start_odometer=1.0, end_odometer=9.0),
        ], "telemetry", 1)
        old = now - timedelta(days=40)
        repo.replace_sessions(conn, a, v, now - timedelta(hours=1, minutes=30), now - timedelta(hours=1, minutes=20), [
            Session("drive", now - timedelta(hours=1, minutes=25), now - timedelta(hours=1, minutes=21),
                    start_odometer=22.0, end_odometer=40.0)], "teslafi_import", 1)
        assert old
    sent = []
    cfg = RuleConfig(unlocked_enabled=False, windows_enabled=False, tires_enabled=False, software_enabled=False)
    r1 = alerts.run_once(engine, a, lambda t, b: sent.append(b), now=now, rule_config=cfg)
    assert sorted(c.detail.split(" ")[0] for c in r1["fired"]) == ["Charge", "Drive"]
    r2 = alerts.run_once(engine, a, lambda t, b: sent.append(b), now=now + timedelta(minutes=1), rule_config=cfg)
    assert r2["fired"] == [] and len(sent) == 2
    r3 = alerts.run_once(engine, a, lambda t, b: sent.append(b), now=now + timedelta(days=2), rule_config=cfg)
    assert r3["resolved"] == [] and len(sent) == 2
