from datetime import UTC, datetime

from teslai.worker import normalize_value, parse_message

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
VIN = "5YJYGDEE1LF000001"


def test_vehicle_field_uses_received_time_and_json_value():
    p = parse_message(f"telemetry/{VIN}/v/BatteryLevel", b"62.5", NOW)
    assert (p.vin, p.kind, p.field, p.value, p.ts) == (VIN, "v", "BatteryLevel", 62.5, NOW)


def test_enum_string_and_location_normalized():
    assert parse_message(f"telemetry/{VIN}/v/Gear", b'"ShiftStateD"', NOW).value == "ShiftStateD"
    loc = parse_message(f"telemetry/{VIN}/v/Location", b'{"Latitude": 39.1, "Longitude": -94.6}', NOW)
    assert loc.value == {"latitude": 39.1, "longitude": -94.6}
    assert normalize_value({"invalid": True}) is None


def test_connectivity_uses_created_at():
    body = b'{"ConnectionId":"abc","Status":"DISCONNECTED","CreatedAt":"2026-09-15T11:59:30Z"}'
    p = parse_message(f"telemetry/{VIN}/connectivity", body, NOW)
    assert p.connected is False and p.ts == datetime(2026, 9, 15, 11, 59, 30, tzinfo=UTC)


def test_malformed_topics_and_payloads_are_ignored():
    assert parse_message("telemetry/SHORTVIN/v/Gear", b'"x"', NOW) is None
    assert parse_message(f"telemetry/{VIN}/v/Gear", b"{not json", NOW) is None
    assert parse_message(f"telemetry/{VIN}/v/a/b", b"1", NOW) is None
    assert parse_message(f"telemetry/{VIN}/connectivity", b'{"Status":"weird"}', NOW) is None
    assert parse_message("other/thing", b"1", NOW) is None


def test_alerts_and_errors_are_passed_through():
    p = parse_message(f"telemetry/{VIN}/errors/stream", b'{"Name":"x","Body":"y"}', NOW)
    assert p.kind == "errors" and p.field == "stream"
