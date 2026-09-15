"""TeslaFi CSV importer.

TeslaFi exports raw logged samples as CSV rows, one full snapshot per row, with
local timestamps and no UTC offset. This module turns those rows into
(utc_timestamp, telemetry-named fields) pairs plus connectivity changes, and a
report of everything it skipped or had to disambiguate.

Timestamp conversion runs in file order:

    local naive "2025-11-02 01:30:00"
        │  ZoneInfo(tz), fold=0 and fold=1
        ▼
    both UTC candidates ── pick the earliest candidate >= previous UTC timestamp
        │                   (fall-back hour: first pass takes fold=0, repeat takes fold=1)
        ▼
    nonexistent local time (spring-forward gap) ── shifted forward, counted in report

The column map below reflects the TeslaFi export format as documented by other
importers. Verify it against a real export before the history gate; a missing
required column fails loudly with TSL-IMPORT-SCHEMA instead of importing garbage.
"""

import csv
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from teslai.errors import TeslaiError

DATE_COLUMN = "Date"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# TeslaFi column -> (telemetry field name, parser)
REQUIRED_COLUMNS = {
    DATE_COLUMN, "state", "shift_state", "speed", "odometer", "battery_level",
    "charging_state", "latitude", "longitude",
}


def _float(v: str) -> float | None:
    return None if v is None or v.strip() in ("", "None", "none", "null") else float(v)


def _bool(v: str) -> bool | None:
    s = (v or "").strip().lower()
    if s in ("", "none", "null"):
        return None
    if s in ("1", "true", "yes"):
        return True
    if s in ("0", "false", "no"):
        return False
    raise ValueError(f"not a boolean: {v!r}")


def _text(v: str) -> str | None:
    s = (v or "").strip()
    return None if s in ("", "None", "none", "null") else s


COLUMN_MAP: dict[str, tuple[str, object]] = {
    "shift_state": ("Gear", _text),
    "speed": ("VehicleSpeed", _float),
    "odometer": ("Odometer", _float),
    "battery_level": ("BatteryLevel", _float),
    "usable_battery_level": ("BatteryLevel", _float),
    "charging_state": ("DetailedChargeState", _text),
    "battery_range": ("RatedRange", _float),
    "ideal_battery_range": ("IdealBatteryRange", _float),
    "est_battery_range": ("EstBatteryRange", _float),
    "charger_power": ("ACChargingPower", _float),
    "charger_voltage": ("ChargerVoltage", _float),
    "charger_actual_current": ("ChargeAmps", _float),
    "charge_limit_soc": ("ChargeLimitSoc", _float),
    "fast_charger_present": ("FastChargerPresent", _bool),
    "inside_temp": ("InsideTemp", _float),
    "outside_temp": ("OutsideTemp", _float),
    "is_climate_on": ("HvacPower", _bool),
    "locked": ("Locked", _bool),
    "sentry_mode": ("SentryMode", _bool),
    "car_version": ("Version", _text),
}
ONLINE_STATES = {"online", "driving", "charging"}
OFFLINE_STATES = {"asleep", "offline", "sleeping"}


@dataclass
class ImportedRow:
    line: int
    ts: datetime
    fields: dict[str, object]
    connected: bool | None


@dataclass
class ImportReport:
    path: Path
    rows_read: int = 0
    rows_imported: int = 0
    skipped: list[tuple[int, str]] = field(default_factory=list)
    ambiguous_resolved: int = 0
    nonexistent_shifted: int = 0
    out_of_order: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None


def resolve_timezone(name: str | None) -> ZoneInfo:
    if not name:
        raise TeslaiError("TSL-IMPORT-TZ", "no --tz given")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise TeslaiError("TSL-IMPORT-TZ", f"unknown timezone {name!r}") from None


def _offset_change_instant(lo: datetime, hi: datetime, tz: ZoneInfo) -> datetime:
    """Binary-search the UTC instant in [lo, hi] where the zone's offset changes."""
    before = lo.astimezone(tz).utcoffset()
    while hi - lo > timedelta(seconds=1):
        mid = lo + (hi - lo) / 2
        if mid.astimezone(tz).utcoffset() == before:
            lo = mid
        else:
            hi = mid
    return hi.replace(microsecond=0)


def to_utc(local: datetime, tz: ZoneInfo, previous: datetime | None,
           report: ImportReport) -> datetime:
    """Convert a naive local time to UTC, keeping file order increasing where possible."""
    c0 = local.replace(tzinfo=tz, fold=0)
    c1 = local.replace(tzinfo=tz, fold=1)
    u0, u1 = c0.astimezone(UTC), c1.astimezone(UTC)
    if u0 == u1:
        return u0

    early, late = sorted((u0, u1))
    round_trips = early.astimezone(tz).replace(tzinfo=None) == local
    if not round_trips:
        # Spring-forward gap: this wall-clock time never happened. Place it at the
        # moment the clocks changed, which lies between its real neighbours.
        report.nonexistent_shifted += 1
        return _offset_change_instant(early, late, tz)

    # Fall-back hour: the wall-clock time happened twice.
    report.ambiguous_resolved += 1
    if previous is not None and previous > early:
        return late
    return early


def read_rows(path: Path, tz_name: str | None) -> tuple[Iterator[ImportedRow], ImportReport]:
    tz = resolve_timezone(tz_name)
    report = ImportReport(path=path)

    def gen() -> Iterator[ImportedRow]:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            header = set(reader.fieldnames or [])
            missing = sorted(REQUIRED_COLUMNS - header)
            if missing:
                raise TeslaiError("TSL-IMPORT-SCHEMA",
                                  f"{path.name} is missing columns: {', '.join(missing)}")
            previous: datetime | None = None
            for line, row in enumerate(reader, start=2):
                report.rows_read += 1
                try:
                    # TeslaFi timestamps carry no offset; to_utc() applies the zone.
                    local = datetime.strptime(  # noqa: DTZ007
                        row[DATE_COLUMN].strip(), DATE_FORMAT)
                except ValueError:
                    report.skipped.append((line, f"bad date {row[DATE_COLUMN]!r}"))
                    continue
                ts = to_utc(local, tz, previous, report)
                if previous is not None and ts < previous:
                    report.out_of_order += 1
                fields: dict[str, object] = {}
                try:
                    for col, (name, parse) in COLUMN_MAP.items():
                        if col in row and name not in fields:
                            value = parse(row[col])  # type: ignore[operator]
                            if value is not None:
                                fields[name] = value
                    lat, lon = _float(row["latitude"]), _float(row["longitude"])
                except ValueError as err:
                    report.skipped.append((line, str(err)))
                    continue
                if lat is not None and lon is not None:
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        report.skipped.append((line, f"location out of range {lat},{lon}"))
                        continue
                    fields["Location"] = {"latitude": lat, "longitude": lon}
                state = (_text(row["state"]) or "").lower()
                connected = (True if state in ONLINE_STATES
                             else False if state in OFFLINE_STATES else None)
                previous = ts if previous is None else max(previous, ts)
                report.rows_imported += 1
                report.first_ts = report.first_ts or ts
                report.last_ts = ts
                yield ImportedRow(line, ts, fields, connected)

    return gen(), report


def month_key(ts: datetime) -> str:
    return f"{ts:%Y-%m}"



def to_events(rows, vehicle_id: int):
    """Convert imported rows into builder inputs.

    Every CSV row is a full snapshot, so each field becomes an event at the row's
    timestamp; the reducer ignores repeats. Connectivity is emitted only when the
    row's online/asleep state changes.
    """
    from teslai.builder import Connectivity
    from teslai.reducer import Event

    events: list[Event] = []
    connectivity: list[Connectivity] = []
    last_connected: bool | None = None
    for r in rows:
        if r.connected is not None and r.connected != last_connected:
            connectivity.append(Connectivity(r.ts, r.connected))
            last_connected = r.connected
        for name, value in r.fields.items():
            events.append(Event(vehicle_id, r.ts, name, value, "teslafi_import"))
    return events, connectivity
