from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from teslai import insights
from teslai.days import _session_json

TZ = ZoneInfo("America/Chicago")
T0 = datetime(2026, 6, 3, 14, tzinfo=UTC)


def row(kind, start, minutes, **kw):
    base = {"id": 1, "kind": kind, "start_ts": start, "end_ts": start + timedelta(minutes=minutes),
            "start_odometer": None, "end_odometer": None, "start_battery": None, "end_battery": None,
            "energy_added_kwh": None, "charger": None, "flags": []}
    base.update(kw)
    return _session_json(base, TZ, None)


def drive(start, miles, kwh, temp_c=20.0, minutes=20, speed=30.0, flags=()):
    return row("drive", start, minutes, start_odometer=100.0, end_odometer=100.0 + miles,
               energy_used_kwh=kwh, avg_outside_temp=temp_c, avg_speed=speed, flags=list(flags))


def test_session_json_derives_drive_efficiency():
    s = row("drive", T0, 30, start_odometer=10.0, end_odometer=30.0, energy_used_kwh=5.0, rated_miles_used=25.0)
    assert (s["distance_miles"], s["wh_per_mile"], s["efficiency_pct"], s["duration_s"]) == (20.0, 250.0, 80.0, 1800.0)


def test_aggregate_by_day_skips_short_drives_and_weights_temperature():
    sessions = [drive(T0, 10, 2.5, temp_c=10, minutes=10), drive(T0 + timedelta(hours=1), 30, 9.0, temp_c=30, minutes=30),
                drive(T0 + timedelta(hours=2), 0.1, 0.1, flags=["short"]),
                row("charge", T0 + timedelta(hours=3), 60, energy_added_kwh=12.0),
                row("sleep", T0 + timedelta(hours=5), 300, start_battery=70.0, end_battery=69.0)]
    [day] = insights.aggregate(sessions, 10).values()
    assert (day["drives"], day["miles"], day["charges"], day["kwh_added"]) == (2, 40.0, 1, 12.0)
    assert day["wh_per_mile"] == 287.5 and day["avg_outside_temp_c"] == 25.0
    assert day["sleep_seconds"] == 18000 and day["parked_drain_pct"] == 1.0


def test_calendar_fills_every_day_and_summarizes():
    cal = insights.calendar([drive(T0, 12, 3.0)], date(2026, 6, 1), date(2026, 6, 30))
    assert len(cal["days"]) == 30 and cal["days"][2]["drives"] == 1 and cal["days"][0]["drives"] == 0
    assert cal["summary"]["days_driven"] == 1 and cal["summary"]["wh_per_mile"] == 250.0


def test_efficiency_buckets_by_temperature_and_speed():
    out = insights.efficiency([drive(T0, 10, 2.5, temp_c=20, speed=35), drive(T0, 10, 3.5, temp_c=22, speed=62),
                               drive(T0, 0.5, 1.0)])
    assert out["temperature"] == [{"temp_f": 60, "temp_f_to": 70, "drives": 1, "miles": 10.0, "wh_per_mile": 250.0},
                                  {"temp_f": 60 + 10, "temp_f_to": 80, "drives": 1, "miles": 10.0, "wh_per_mile": 350.0}]
    assert [b["speed_mph"] for b in out["speed"]] == [30, 60]


def test_charge_locations_group_and_name_unknowns():
    out = insights.charge_locations([
        row("charge", T0, 60, energy_added_kwh=10.0, end_place="Home", charger="ac"),
        row("charge", T0 + timedelta(days=1), 60, energy_added_kwh=20.0, end_place="Home", charger="ac"),
        row("charge", T0, 30, energy_added_kwh=40.0, charger="dc")])
    assert [(g["location"], g["charges"], g["kwh_added"]) for g in out] == [("Unnamed Supercharger", 1, 40.0), ("Home", 2, 30.0)]
    assert out[1]["chargers"] == ["ac"]


def test_tracks_assign_samples_to_drives_and_thin():
    drives = [{"id": 1, "start_ts": T0, "end_ts": T0 + timedelta(minutes=10)},
              {"id": 2, "start_ts": T0 + timedelta(hours=1), "end_ts": T0 + timedelta(hours=1, minutes=5)}]
    samples = [{"ts": T0 + timedelta(seconds=10 * i), "latitude": 30 + i / 1000, "longitude": -97.0} for i in range(61)]
    samples += [{"ts": T0 + timedelta(minutes=30), "latitude": 1.0, "longitude": 1.0}]
    [t] = insights.tracks(drives, samples, max_points=10)
    assert t["id"] == 1 and len(t["points"]) <= 11 and t["points"][-1] == [-97.0, 30.06]
