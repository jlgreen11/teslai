from datetime import UTC, datetime, timedelta

from teslai.config import load_field_specs
from teslai.reducer import Event, StateReducer

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def ev(field, value, minutes=0.0, seconds=0.0):
    return Event(1, T0 + timedelta(minutes=minutes, seconds=seconds), field, value)


def reducer():
    return StateReducer(load_field_specs())


def test_gear_sent_once_stays_valid_for_whole_drive():
    r = reducer()
    r.apply(ev("Gear", "ShiftStateD"))
    for m in range(41):
        r.apply(ev("VehicleSpeed", 60 + (m % 3), minutes=m))
    assert r.value(T0 + timedelta(minutes=40), "Gear") == "ShiftStateD"


def test_speed_goes_stale_when_updates_stop():
    r = reducer()
    r.apply(ev("VehicleSpeed", 55))
    assert r.value(T0 + timedelta(seconds=299), "VehicleSpeed") == 55
    assert r.value(T0 + timedelta(seconds=301), "VehicleSpeed") is None


def test_battery_level_without_stale_limit_carries_forward_while_connected():
    r = reducer()
    r.apply(ev("BatteryLevel", 70.0))
    assert r.value(T0 + timedelta(hours=10), "BatteryLevel") == 70.0


def test_disconnect_invalidates_every_field():
    r = reducer()
    r.apply(ev("Gear", "ShiftStateP"))
    r.apply(ev("BatteryLevel", 62.4))
    r.connectivity(T0 + timedelta(minutes=5), connected=False)
    at = T0 + timedelta(minutes=6)
    assert r.value(at, "Gear") is None
    assert r.value(at, "BatteryLevel") is None
    snap = r.snapshot(at)
    assert snap["BatteryLevel"].value == 62.4 and snap["BatteryLevel"].valid is False


def test_events_older_than_disconnect_do_not_revive_state():
    r = reducer()
    r.connectivity(T0 + timedelta(minutes=5), connected=False)
    assert r.apply(ev("Gear", "ShiftStateD", minutes=4)) is False
    assert r.apply(ev("Gear", "ShiftStateP", minutes=6)) is True
    assert r.value(T0 + timedelta(minutes=7), "Gear") == "ShiftStateP"


def test_duplicate_and_out_of_order_events_are_idempotent():
    events = [ev("Gear", "ShiftStateD", 1), ev("Gear", "ShiftStateP", 30),
              ev("BatteryLevel", 80, 2), ev("BatteryLevel", 75, 29)]
    a, b = reducer(), reducer()
    for e in events:
        a.apply(e)
    for e in reversed(events + events):
        b.apply(e)
    at = T0 + timedelta(minutes=31)
    assert a.snapshot(at) == b.snapshot(at)
    assert a.value(at, "Gear") == "ShiftStateP"


def test_snapshot_ignores_values_from_the_future():
    r = reducer()
    r.apply(ev("Gear", "ShiftStateD", minutes=10))
    assert "Gear" not in r.snapshot(T0 + timedelta(minutes=5))


def test_session_reset_clears_state_but_keeps_continuous():
    r = reducer()
    r.apply(ev("Gear", "ShiftStateD"))
    r.apply(ev("Odometer", 31000.0))
    r.reset(T0 + timedelta(minutes=1))
    at = T0 + timedelta(minutes=2)
    assert r.value(at, "Gear") is None
    assert r.value(at, "Odometer") == 31000.0


def test_unknown_field_is_recorded_not_raised():
    r = reducer()
    assert r.apply(ev("BrandNewFirmwareField", 1)) is False
    assert "BrandNewFirmwareField" in r.unknown_fields
