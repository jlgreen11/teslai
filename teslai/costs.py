"""Charging cost and gas savings.

    charge session (start, end, kWh added, place kind)
        │  energy spread evenly over the session in 15-minute slices
        ▼                (the charge curve is not known for history imports)
    price per slice:
        home          time-of-use window in local time, else the home default
        free          0
        supercharger  default per-kWh price; a downloaded invoice overrides the total
        public        public default
        ▼
    cost = Σ slice kWh × slice price

Gas savings compare the miles driven with what the same miles would have cost
in a gas car, minus the electricity cost.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml

from teslai.paths import CONFIG_DIR

PlaceKind = Literal["home", "free", "supercharger", "public"]
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SLICE = timedelta(minutes=15)


@dataclass(frozen=True)
class Window:
    days: frozenset[int]
    start: time
    end: time | None  # None means end of day ("24:00")
    price_per_kwh: float

    def matches(self, local: datetime) -> bool:
        t = local.time()
        end = self.end
        if end is None or self.start < end:
            return local.weekday() in self.days and self.start <= t and (end is None or t < end)
        # Crosses midnight: the part after midnight belongs to the previous day's window.
        if t >= self.start:
            return local.weekday() in self.days
        return t < end and (local.weekday() - 1) % 7 in self.days


@dataclass(frozen=True)
class Tariffs:
    currency: str
    home_default: float
    home_windows: tuple[Window, ...]
    public_default: float
    supercharger_default: float
    free_places: frozenset[str] = field(default_factory=frozenset)
    gas_price_per_gallon: float = 0.0
    gas_mpg: float = 0.0

    def price_at(self, kind: PlaceKind, local: datetime) -> float:
        if kind == "free":
            return 0.0
        if kind == "supercharger":
            return self.supercharger_default
        if kind == "public":
            return self.public_default
        for w in self.home_windows:
            if w.matches(local):
                return w.price_per_kwh
        return self.home_default


def _parse_time(value: str, name: str) -> time | None:
    if value == "24:00":
        return None
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except ValueError:
        raise ValueError(f"{name}: time must be HH:MM, got {value!r}") from None


def load_tariffs(path: Path | None = None) -> Tariffs:
    if path is None:
        path = CONFIG_DIR / "tariffs.yaml"
        if not path.exists():
            path = CONFIG_DIR / "tariffs.example.yaml"
    raw = yaml.safe_load(path.read_text()) or {}
    windows = []
    for i, w in enumerate((raw.get("home") or {}).get("schedules") or []):
        days = w.get("days") or DAYS
        bad = [d for d in days if d not in DAYS]
        if bad:
            raise ValueError(f"home.schedules[{i}]: unknown days {bad}")
        start = _parse_time(str(w["start"]), f"home.schedules[{i}].start")
        if start is None:
            raise ValueError(f"home.schedules[{i}].start cannot be 24:00")
        windows.append(Window(frozenset(DAYS.index(d) for d in days), start,
                              _parse_time(str(w["end"]), f"home.schedules[{i}].end"),
                              float(w["price_per_kwh"])))
    gas = raw.get("gas") or {}
    return Tariffs(
        currency=raw.get("currency", "USD"),
        home_default=float((raw.get("home") or {}).get("default_price_per_kwh", 0.0)),
        home_windows=tuple(windows),
        public_default=float((raw.get("public") or {}).get("default_price_per_kwh", 0.0)),
        supercharger_default=float((raw.get("supercharger") or {}).get("default_price_per_kwh", 0.0)),
        free_places=frozenset(raw.get("free_places") or []),
        gas_price_per_gallon=float(gas.get("price_per_gallon", 0.0)),
        gas_mpg=float(gas.get("mpg", 0.0)),
    )


def charge_cost(start: datetime, end: datetime, kwh: float, kind: PlaceKind, tz: ZoneInfo,
                tariffs: Tariffs, invoice_total: float | None = None) -> float:
    """Cost of one charge session. An invoice total, when known, always wins."""
    if invoice_total is not None:
        return round(invoice_total, 2)
    if kwh <= 0 or end <= start:
        return 0.0
    duration = end - start
    total = 0.0
    t = start
    while t < end:
        slice_end = min(t + SLICE, end)
        share = (slice_end - t) / duration
        total += kwh * share * tariffs.price_at(kind, t.astimezone(tz))
        t = slice_end
    return round(total, 2)


def gas_savings(miles: float, electricity_cost: float, tariffs: Tariffs) -> float:
    if tariffs.gas_mpg <= 0 or miles <= 0:
        return 0.0
    gas_cost = miles / tariffs.gas_mpg * tariffs.gas_price_per_gallon
    return round(gas_cost - electricity_cost, 2)
