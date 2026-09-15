import random
from datetime import UTC, datetime, timedelta

from teslai.builder import BuilderParams, Connectivity, build_sessions
from teslai.reducer import Event

T0 = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def t(minutes=0.0, seconds=0.0):
    return T0 + timedelta(minutes=minutes, seconds=seconds)


def e(field, value, minutes=0.0, seconds=0.0, source="telemetry"):
    return Event(1, t(minutes, seconds), field, value, source)


def drive_events(start_min, end_min, odo_start=31000.0, miles=20.0):
    evs = [e("Gear", "ShiftStateD", start_min), e("Odometer", odo_start, start_min)]
    steps = int(end_min - start_min)
    for i in range(1, steps + 1):
        evs.append(e("VehicleSpeed", 50 + (i % 5), start_min + i))
        evs.append(e("Odometer", odo_start + miles * i / steps, start_min + i))
    evs.append(e("VehicleSpeed", 0, end_min, 30))
    evs.append(e("Gear", "ShiftStateP", end_min, 40))
    return evs


def kinds(sessions):
    return [s.kind for s in sessions]


def test_simple_day_idle_drive_idle_sleep():
    evs = [e("BatteryLevel", 80, 0), *drive_events(5, 45)]
    conn = [Connectivity(t(0), True), Connectivity(t(90), False)]
    s = build_sessions(evs, conn, until=t(120))
    assert kinds(s) == ["idle", "drive", "idle", "sleep"]
    drive = s[1]
    assert drive.start == t(5) and drive.end == t(45, 40)
    assert round(drive.distance, 1) == 20.0
    assert s[3].end is None


def test_gear_sent_once_for_forty_minutes_is_one_drive():
    evs = drive_events(1, 41)
    assert sum(1 for x in evs if x.field == "Gear") == 2
    s = build_sessions(evs, [Connectivity(t(0), True)], until=t(60))
    assert kinds(s).count("drive") == 1


def test_invalid_gear_blip_while_parked_is_not_a_drive():
    evs = [e("Gear", "ShiftStateP", 0), e("Odometer", 100.0, 0), e("Gear", "ShiftStateInvalid", 5),
           e("Gear", "ShiftStateP", 5, 3), e("BatteryLevel", 70, 10)]
    s = build_sessions(evs, [Connectivity(t(0), True)], until=t(20))
    assert kinds(s) == ["idle"]


def test_shift_to_drive_and_back_without_moving_is_not_a_drive():
    evs = [e("Gear", "ShiftStateP", 0), e("Odometer", 100.0, 0), e("Gear", "ShiftStateD", 5),
           e("VehicleSpeed", 0, 5, 1), e("Gear", "ShiftStateP", 5, 20), e("BatteryLevel", 70, 6)]
    s = build_sessions(evs, [Connectivity(t(0), True)], until=t(20))
    assert "drive" not in kinds(s)


def test_brief_park_during_drive_does_not_split_it():
    evs = drive_events(0, 30)
    evs = [x for x in evs if not (x.field == "Gear" and x.value == "ShiftStateP")]
    evs += [e("Gear", "ShiftStateP", 10), e("Gear", "ShiftStateD", 10, 30),
            e("Gear", "ShiftStateP", 31)]
    s = build_sessions(evs, [Connectivity(t(0), True)], until=t(40))
    assert kinds(s).count("drive") == 1


def test_charge_then_top_up_after_complete_is_two_charges():
    evs = [e("Odometer", 500.0, 0), e("BatteryLevel", 50, 0),
           e("DetailedChargeState", "DetailedChargeStateCharging", 10),
           e("ACChargingEnergyIn", 0.0, 10), e("ACChargingEnergyIn", 20.0, 100),
           e("BatteryLevel", 80, 100),
           e("DetailedChargeState", "DetailedChargeStateComplete", 101),
           e("DetailedChargeState", "DetailedChargeStateCharging", 300),
           e("ACChargingEnergyIn", 0.0, 300, 5), e("ACChargingEnergyIn", 1.5, 320),
           e("DetailedChargeState", "DetailedChargeStateComplete", 321)]
    s = build_sessions(evs, [Connectivity(t(0), True)], until=t(400))
    charges = [x for x in s if x.kind == "charge"]
    assert len(charges) == 2
    assert charges[0].energy_added_kwh == 20.0 and charges[0].charger == "ac"
    assert charges[1].energy_added_kwh == 1.5


def test_counter_reset_mid_charge_opens_new_session():
    evs = [e("DetailedChargeState", "DetailedChargeStateCharging", 0),
           e("DCChargingEnergyIn", 0.0, 0), e("DCChargingEnergyIn", 30.0, 20),
           e("DCChargingEnergyIn", 0.2, 25), e("DCChargingEnergyIn", 10.0, 35),
           e("DetailedChargeState", "DetailedChargeStateComplete", 36)]
    s = build_sessions(evs, [Connectivity(t(0), True)], until=t(60))
    charges = [x for x in s if x.kind == "charge"]
    assert [c.energy_added_kwh for c in charges] == [30.0, 9.8]
    assert "counter_reset" in charges[0].flags and charges[0].charger == "dc"


def test_disconnect_during_server_downtime_is_unreachable_not_sleep():
    downtime = [(t(30), t(90))]
    conn = [Connectivity(t(0), True), Connectivity(t(40), False), Connectivity(t(80), True)]
    s = build_sessions([e("BatteryLevel", 60, 1)], conn, until=t(100), server_downtime=downtime)
    assert kinds(s) == ["idle", "unreachable", "idle"]


def test_offline_during_drive_ends_drive_after_limit():
    evs = drive_events(0, 30)
    evs = [x for x in evs if x.ts <= t(15)]
    conn = [Connectivity(t(0), True), Connectivity(t(15, 30), False), Connectivity(t(60), True)]
    s = build_sessions(evs, conn, until=t(70))
    assert kinds(s) == ["drive", "sleep", "idle"]
    assert "ended_offline" in s[0].flags and s[0].end == t(15, 30)


def test_short_offline_tunnel_keeps_drive_open():
    evs = drive_events(0, 30)
    conn = [Connectivity(t(0), True), Connectivity(t(10), False), Connectivity(t(12), True)]
    s = build_sessions(evs, conn, until=t(40), params=BuilderParams(offline_end_drive_s=600))
    assert kinds(s).count("drive") == 1


def test_rebuild_is_order_and_duplicate_independent():
    evs = [e("BatteryLevel", 80, 0), *drive_events(5, 45),
           e("DetailedChargeState", "DetailedChargeStateCharging", 60),
           e("ACChargingEnergyIn", 0.0, 60), e("ACChargingEnergyIn", 7.0, 120),
           e("DetailedChargeState", "DetailedChargeStateComplete", 121)]
    conn = [Connectivity(t(0), True), Connectivity(t(200), False)]
    base = build_sessions(evs, conn, until=t(240))
    shuffled = evs + evs
    random.Random(7).shuffle(shuffled)
    again = build_sessions(shuffled, list(reversed(conn)), until=t(240))
    assert [(x.kind, x.start, x.end, x.energy_added_kwh) for x in base] == \
           [(x.kind, x.start, x.end, x.energy_added_kwh) for x in again]


def test_teslafi_enum_values_use_teslafi_mapping():
    evs = [e("Gear", "D", 1, source="teslafi_import"), e("Odometer", 10.0, 1, source="teslafi_import"),
           e("Odometer", 12.0, 5, source="teslafi_import"),
           e("Gear", "P", 10, source="teslafi_import")]
    s = build_sessions(evs, [Connectivity(t(0), True)], until=t(20))
    assert kinds(s) == ["idle", "drive", "idle"]


def test_sessions_capture_start_and_end_locations():
    evs = [e("Location", {"latitude": 39.0, "longitude": -94.5}, 0), *drive_events(5, 45),
           e("Location", {"latitude": 39.2, "longitude": -94.7}, 44)]
    s = build_sessions(evs, [Connectivity(t(0), True)], until=t(60))
    drive = next(x for x in s if x.kind == "drive")
    assert drive.start_location == {"latitude": 39.0, "longitude": -94.5}
    assert drive.end_location == {"latitude": 39.2, "longitude": -94.7}
