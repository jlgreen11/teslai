from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from teslai.costs import charge_cost, gas_savings, load_tariffs

CHI = ZoneInfo("America/Chicago")


def tariffs(tmp_path, body):
    p = tmp_path / "t.yaml"
    p.write_text(body)
    return load_tariffs(p)


TOU = """
home:
  default_price_per_kwh: 0.20
  schedules:
    - {days: [mon, tue, wed, thu, fri], start: "21:00", end: "06:00", price_per_kwh: 0.05}
    - {days: [sat, sun], start: "00:00", end: "24:00", price_per_kwh: 0.10}
public: {default_price_per_kwh: 0.30}
supercharger: {default_price_per_kwh: 0.40}
gas: {price_per_gallon: 3.00, mpg: 30}
"""


def local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=CHI).astimezone(UTC)


def test_shipped_example_loads():
    t = load_tariffs()
    assert t.home_default > 0 and t.home_windows


def test_price_windows_weekday_weekend_and_cross_midnight(tmp_path):
    t = tariffs(tmp_path, TOU)
    # Wednesday 2026-09-16
    assert t.price_at("home", datetime(2026, 9, 16, 12, tzinfo=CHI)) == 0.20
    assert t.price_at("home", datetime(2026, 9, 16, 22, tzinfo=CHI)) == 0.05
    assert t.price_at("home", datetime(2026, 9, 17, 3, tzinfo=CHI)) == 0.05   # Thu 3am, Wed window
    # Saturday 3am after Friday night: Friday window crosses into Saturday
    assert t.price_at("home", datetime(2026, 9, 19, 3, tzinfo=CHI)) == 0.05
    # Monday 3am: Sunday is not in the weekday window, so the weekend all-day price does not apply
    assert t.price_at("home", datetime(2026, 9, 21, 3, tzinfo=CHI)) == 0.20
    assert t.price_at("home", datetime(2026, 9, 20, 23, 59, tzinfo=CHI)) == 0.10


def test_charge_cost_splits_across_tou_boundary(tmp_path):
    t = tariffs(tmp_path, TOU)
    # Wed 20:00-22:00 local, 20 kWh: first hour at 0.20, second at 0.05
    cost = charge_cost(local(2026, 9, 16, 20), local(2026, 9, 16, 22), 20.0, "home", CHI, t)
    assert cost == pytest.approx(10 * 0.20 + 10 * 0.05)


def test_free_supercharger_public_and_invoice_override(tmp_path):
    t = tariffs(tmp_path, TOU)
    s, e = local(2026, 9, 16, 12), local(2026, 9, 16, 13)
    assert charge_cost(s, e, 30, "free", CHI, t) == 0.0
    assert charge_cost(s, e, 30, "supercharger", CHI, t) == 12.0
    assert charge_cost(s, e, 30, "public", CHI, t) == 9.0
    assert charge_cost(s, e, 30, "supercharger", CHI, t, invoice_total=0.0) == 0.0
    assert charge_cost(s, s, 30, "home", CHI, t) == 0.0


def test_dst_night_charge_uses_local_wall_clock(tmp_path):
    t = tariffs(tmp_path, TOU)
    # Sat 2025-11-01 23:00 CDT to Sun 01:30 CST spans the repeated hour; all weekend price.
    cost = charge_cost(datetime(2025, 11, 2, 4, tzinfo=UTC), datetime(2025, 11, 2, 7, 30, tzinfo=UTC),
                       35.0, "home", CHI, t)
    assert cost == pytest.approx(35 * 0.10)


def test_gas_savings(tmp_path):
    t = tariffs(tmp_path, TOU)
    assert gas_savings(300, 12.0, t) == pytest.approx(300 / 30 * 3.0 - 12.0)
    assert gas_savings(0, 5.0, t) == 0.0


def test_invalid_config_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown days"):
        tariffs(tmp_path, "home:\n  schedules:\n    - {days: [funday], start: '01:00', end: '02:00', price_per_kwh: 1}\n")
    with pytest.raises(ValueError, match="HH:MM"):
        tariffs(tmp_path, "home:\n  schedules:\n    - {start: 'noon', end: '02:00', price_per_kwh: 1}\n")
