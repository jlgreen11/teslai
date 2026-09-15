from datetime import UTC, datetime, timedelta

import pytest

from teslai.alerts import format_alert
from teslai.places import Place
from teslai.reducer import FieldValue
from teslai.rules import RuleConfig, evaluate, load_rule_config

NOW = datetime(2026, 9, 15, 20, tzinfo=UTC)
HOME = Place("Home", "home", 39.0, -94.5, 80, id=1)
AWAY = {"latitude": 39.3, "longitude": -94.9}
AT_HOME = {"latitude": 39.0001, "longitude": -94.5}
CFG = RuleConfig()


def fv(value, minutes_ago=30):
    return FieldValue(value, NOW - timedelta(minutes=minutes_ago))


def codes(conds):
    return sorted(c.code for c in conds)


def base(**overrides):
    state = {"Gear": fv("ShiftStateP"), "Locked": fv(True), "Location": fv(AWAY),
             "FdWindow": fv("WindowStateClosed"), "TpmsPressureFl": fv(2.9)}
    state.update(overrides)
    return state


def test_unlocked_away_fires_after_limit_but_not_at_home_or_briefly_or_driving():
    assert codes(evaluate(1, "0001", base(Locked=fv(False, 15)), True, NOW, [HOME], CFG)) == ["TSL-CAR-UNLOCKED"]
    assert evaluate(1, "0001", base(Locked=fv(False, 15), Location=fv(AT_HOME)), True, NOW, [HOME], CFG) == []
    assert evaluate(1, "0001", base(Locked=fv(False, 5)), True, NOW, [HOME], CFG) == []
    assert evaluate(1, "0001", base(Locked=fv(False, 15), Gear=fv("ShiftStateD")), True, NOW, [HOME], CFG) == []


def test_asleep_car_uses_last_known_state():
    conds = evaluate(1, "0001", base(Locked=fv(False, 90), Gear=fv("ShiftStateD", 95)), False, NOW, [HOME], CFG)
    assert codes(conds) == ["TSL-CAR-UNLOCKED"]


def test_windows_and_tires():
    conds = evaluate(1, "0001", base(FdWindow=fv("WindowStatePartiallyOpen", 20), TpmsPressureFl=fv(2.2),
                                     TpmsPressureRr=fv(3.9)), True, NOW, [HOME], CFG)
    assert codes(conds) == ["TSL-TIRE-PRESSURE", "TSL-TIRE-PRESSURE", "TSL-WINDOW-OPEN"]
    assert {c.key for c in conds if c.rule == "tire_pressure"} == {"1:TpmsPressureFl", "1:TpmsPressureRr"}


def test_new_software_is_informational_and_keyed_by_version():
    [c] = evaluate(1, "0001", base(Version=fv("2026.26.6.5")), True, NOW, [HOME], CFG)
    assert c.informational and c.key == "1:2026.26.6.5"
    _title, body = format_alert(c)
    assert "Fix:" not in body and "2026.26.6.5" in body


def test_rules_disabled_and_config_validation(tmp_path):
    off = RuleConfig(unlocked_enabled=False, windows_enabled=False, tires_enabled=False, software_enabled=False)
    assert evaluate(1, "0001", base(Locked=fv(False, 60), TpmsPressureFl=fv(1.0), Version=fv("x")), True, NOW, [], off) == []
    assert load_rule_config().unlocked_minutes == 10
    bad = tmp_path / "r.yaml"
    bad.write_text("tire_pressure: {low_bar: 3.0, high_bar: 2.0}\n")
    with pytest.raises(ValueError):
        load_rule_config(bad)
