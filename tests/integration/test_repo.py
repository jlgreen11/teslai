from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text

from teslai.db import repo
from teslai.errors import TeslaiError
from teslai.reducer import Event

pytestmark = pytest.mark.integration
T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _setup(conn):
    a = repo.create_account(conn, "owner")
    v = repo.create_vehicle(conn, a, "TESTVIN0000000001", "Test car", "America/Chicago")
    return a, v


def test_postgis_available(conn):
    assert conn.execute(text("SELECT postgis_version()")).scalar()


def test_duplicate_events_are_ignored(conn):
    a, v = _setup(conn)
    evs = [Event(v, T0, "Gear", "ShiftStateD"), Event(v, T0, "Gear", "ShiftStateD"),
           Event(v, T0 + timedelta(seconds=5), "VehicleSpeed", 42)]
    assert repo.insert_events(conn, a, evs) == 2
    assert repo.insert_events(conn, a, evs) == 0
    got = repo.events_for_vehicle(conn, a, v, T0, T0 + timedelta(minutes=1))
    assert [(e.field, e.value) for e in got] == [("Gear", "ShiftStateD"), ("VehicleSpeed", 42)]


def test_events_are_scoped_to_account(conn):
    a, v = _setup(conn)
    other = repo.create_account(conn, "someone else")
    assert repo.insert_events(conn, other, [Event(v, T0, "Gear", "ShiftStateP")]) == 0
    repo.insert_events(conn, a, [Event(v, T0, "Gear", "ShiftStateP")])
    assert repo.events_for_vehicle(conn, other, v, T0, T0 + timedelta(hours=1)) == []


def test_unknown_vin_is_rejected_with_catalog_code(conn):
    a, _ = _setup(conn)
    with pytest.raises(TeslaiError) as exc:
        repo.vehicle_id_for_vin(conn, a, "NOTMYCAR000000000")
    assert exc.value.info.code == "TSL-VIN-REJECTED"


def test_partition_created_after_rows_landed_in_default(conn):
    a, v = _setup(conn)
    repo.insert_events(conn, a, [Event(v, T0, "BatteryLevel", 70.5)])
    name = repo.ensure_month_partition(conn, date(2026, 9, 1))
    assert name == "telemetry_events_2026_09"
    assert conn.execute(text(f"SELECT count(*) FROM {name}")).scalar() == 1
    assert conn.execute(text("SELECT count(*) FROM telemetry_events_default")).scalar() == 0
    assert repo.ensure_month_partition(conn, date(2026, 9, 1)) == name
    repo.insert_events(conn, a, [Event(v, T0 + timedelta(days=2), "BatteryLevel", 69.0)])
    assert conn.execute(text(f"SELECT count(*) FROM {name}")).scalar() == 2


def test_usage_accumulates(conn):
    a, v = _setup(conn)
    repo.add_usage(conn, a, v, date(2026, 9, 1), "signal", 100, "VehicleSpeed")
    repo.add_usage(conn, a, v, date(2026, 9, 1), "signal", 50, "VehicleSpeed")
    n = conn.execute(text("SELECT count FROM api_usage WHERE field='VehicleSpeed'")).scalar()
    assert n == 150
