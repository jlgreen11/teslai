import json
from datetime import UTC, datetime, timedelta

from teslai.homeassistant import ENTITIES, discovery_messages, state_payload, state_topic
from teslai.reducer import FieldValue

VIN = "5YJYGDEE0SY000001"
NOW = datetime(2026, 9, 15, 20, tzinfo=UTC)


def test_discovery_configs_are_unique_and_point_at_state_topic():
    msgs = discovery_messages(VIN, "Tessie")
    assert len(msgs) == len(ENTITIES)
    configs = [json.loads(p) for _, p in msgs]
    assert len({c["unique_id"] for c in configs}) == len(configs)
    assert all(c["state_topic"] == state_topic(VIN) == "teslai/5yjygdee0sy000001/state" for c in configs)
    assert msgs[0][0] == "homeassistant/sensor/teslai_5yjygdee0sy000001/battery_level/config"
    lock = next(c for t, c in zip([t for t, _ in msgs], configs, strict=True) if "binary_sensor" in t)
    assert lock["device_class"] == "lock" and "OFF" in lock["value_template"]
    assert not any("latitude" in p or "Location" in p for _, p in msgs)


def test_state_payload_totals_and_values():
    state = {"BatteryLevel": FieldValue(62.37, NOW), "RatedRange": FieldValue(182.1, NOW),
             "Odometer": FieldValue(31254.0, NOW), "Locked": FieldValue(True, NOW),
             "Location": FieldValue({"latitude": 1, "longitude": 2}, NOW)}
    t0 = NOW - timedelta(hours=5)
    today = [
        {"kind": "drive", "start_odometer": 100.0, "end_odometer": 112.5, "flags": [], "energy_added_kwh": None},
        {"kind": "drive", "start_odometer": 112.5, "end_odometer": 112.51, "flags": ["short"], "energy_added_kwh": None},
        {"kind": "charge", "start_odometer": None, "end_odometer": None, "flags": [], "energy_added_kwh": 7.25},
    ]
    payload = json.loads(state_payload(state, today, {"start_odometer": 100.0, "end_odometer": 112.5,
                                                      "start_ts": t0}))
    assert payload == {"battery_level": 62.4, "rated_range": 182.1, "odometer": 31254.0,
                       "charging_state": None, "locked": True, "last_drive_miles": 12.5,
                       "today_miles": 12.5, "today_kwh_added": 7.25}
