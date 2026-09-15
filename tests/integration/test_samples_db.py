import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from teslai.builder import Session
from teslai.db import repo
from teslai.samples import enrich_sessions, sample_from_fields, upsert_samples

pytestmark = pytest.mark.integration


def test_upsert_and_enrich_drive_stats(engine):
    tag = uuid.uuid4().hex[:10].upper()
    t0 = datetime(2026, 5, 1, 14, tzinfo=UTC)
    with engine.begin() as conn:
        a = repo.create_account(conn, f"smp-{tag}")
        v = repo.create_vehicle(conn, a, f"SMP{tag}0000"[:17])
        rows = [sample_from_fields(t0 + timedelta(minutes=m), {
            "VehicleSpeed": 30 + m, "OutsideTemp": 20 + m / 10, "InsideTemp": 21, "RatedRange": 250 - m,
            "EnergyRemaining": 60 - m * 0.1, "BatteryLevel": 80 - m * 0.2}) for m in range(21)]
        assert upsert_samples(conn, a, v, rows, "test") == 21
        assert upsert_samples(conn, a, v, rows[:5], "test") == 5
        repo.replace_sessions(conn, a, v, t0 - timedelta(hours=1), t0 + timedelta(hours=1), [
            Session("drive", t0, t0 + timedelta(minutes=20), start_odometer=100.0, end_odometer=110.0,
                    start_battery=80, end_battery=76)], "test", 1)
        enrich_sessions(conn, a, v, t0 - timedelta(hours=1), t0 + timedelta(hours=1))
        d = conn.execute(text("SELECT energy_used_kwh, rated_miles_used, max_speed, round(avg_outside_temp::numeric, 1) AS ot "
                              "FROM sessions WHERE vehicle_id = :v"), {"v": v}).one()
        assert round(d.energy_used_kwh, 2) == 2.0 and d.rated_miles_used == 20 and d.max_speed == 50 and float(d.ot) == 21.0
        assert conn.execute(text("SELECT count(*) FROM samples WHERE vehicle_id = :v"), {"v": v}).scalar() == 21
