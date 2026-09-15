from datetime import UTC, datetime, timedelta

from teslai.reducer import Event
from teslai.samples import sample_from_fields, samples_from_events

T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)


def test_sample_from_fields_maps_columns_and_location():
    s = sample_from_fields(T0, {"Location": {"latitude": 30.1, "longitude": -97.2}, "VehicleSpeed": 42,
                                "Gear": "D", "BatteryLevel": 70, "PackVoltage": 400, "PackCurrent": 50,
                                "DCChargingPower": 120})
    assert (s["latitude"], s["longitude"], s["speed"], s["gear"], s["battery_level"]) == (30.1, -97.2, 42.0, "D", 70.0)
    assert s["power"] == 20.0 and s["charger_power"] == 120.0 and s["tpms_fl"] is None


def test_samples_from_events_throttles_but_keeps_state_changes():
    evs = [Event(1, T0, "Gear", "ShiftStateD")]
    evs += [Event(1, T0 + timedelta(seconds=i), "VehicleSpeed", i) for i in range(1, 60)]
    evs += [Event(1, T0 + timedelta(seconds=61), "Gear", "ShiftStateP")]
    out = samples_from_events(evs)
    assert 6 <= len(out) <= 9
    assert out[-1]["gear"] == "ShiftStateP" and out[-1]["ts"] == T0 + timedelta(seconds=61)
