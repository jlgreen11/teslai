from pathlib import Path

import pytest

from teslai.config import load_enum_table, load_field_specs


def test_shipped_field_specs_load_and_classify():
    specs = load_field_specs()
    assert specs["Gear"].kind == "state"
    assert specs["VehicleSpeed"].kind == "continuous"
    assert specs["VehicleSpeed"].stale_after_seconds == 300
    assert "RouteLine" not in specs
    assert "MinutesToArrival" not in specs
    assert all(s.stale_after_seconds is None for s in specs.values() if s.kind == "state")


def test_state_field_with_stale_limit_is_rejected(tmp_path: Path):
    p = tmp_path / "t.yaml"
    p.write_text("fields:\n  Gear: {kind: state, interval_seconds: 1, stale_after_seconds: 5}\n")
    with pytest.raises(ValueError, match="state fields must not"):
        load_field_specs(p)


def test_unknown_kind_is_rejected(tmp_path: Path):
    p = tmp_path / "t.yaml"
    p.write_text("fields:\n  Gear: {kind: sometimes, interval_seconds: 1}\n")
    with pytest.raises(ValueError, match="kind must be"):
        load_field_specs(p)


def test_enum_meanings_cover_invalid_null_and_unlisted():
    t = load_enum_table()
    assert t.meaning("Gear", "ShiftStateD") == "drive"
    assert t.meaning("Gear", "ShiftStateInvalid") == "unknown"
    assert t.meaning("Gear", "ShiftStateSNA") == "unknown"
    assert t.meaning("Gear", None) == "unknown"
    assert t.meaning("Gear", "ShiftStateSomethingNew") == "unknown"
    assert t.meaning("Gear", "D", source="teslafi") == "drive"
    assert t.meaning("ChargingCableType", "CableTypeInvalid") == "none"
    assert t.meaning("DetailedChargeState", "DetailedChargeStateComplete") == "complete"


def test_enum_overrides_layer_on_shipped_table(tmp_path: Path):
    o = tmp_path / "enums.override.yaml"
    o.write_text("fields:\n  Gear:\n    telemetry:\n      ShiftStateSomethingNew: drive\n")
    t = load_enum_table(overrides=o)
    assert t.meaning("Gear", "ShiftStateSomethingNew") == "drive"
    assert t.meaning("Gear", "ShiftStateP") == "park"
