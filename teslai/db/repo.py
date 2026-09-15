"""The only query path into the database.

Every function takes an account_id and filters by it. When row-level security is
enabled at the sharing gate, this module is where the session variable gets set;
feature code does not change.
"""

import json
from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import Connection, text

from teslai.errors import TeslaiError
from teslai.reducer import Event


def create_account(conn: Connection, name: str) -> int:
    return conn.execute(
        text("INSERT INTO accounts (name) VALUES (:n) RETURNING id"), {"n": name}
    ).scalar_one()


def create_vehicle(conn: Connection, account_id: int, vin: str, display_name: str | None = None,
                   timezone: str = "UTC") -> int:
    return conn.execute(
        text("INSERT INTO vehicles (account_id, vin, display_name, timezone) "
             "VALUES (:a, :v, :d, :tz) RETURNING id"),
        {"a": account_id, "v": vin, "d": display_name, "tz": timezone},
    ).scalar_one()


def vehicle_id_for_vin(conn: Connection, account_id: int, vin: str) -> int:
    """Resolve a VIN owned by this account, or raise TSL-VIN-REJECTED."""
    vid = conn.execute(
        text("SELECT id FROM vehicles WHERE account_id = :a AND vin = :v"),
        {"a": account_id, "v": vin},
    ).scalar_one_or_none()
    if vid is None:
        raise TeslaiError("TSL-VIN-REJECTED", f"VIN ending {vin[-4:]}")
    return vid


def insert_events(conn: Connection, account_id: int, events: Iterable[Event]) -> int:
    """Insert telemetry events, ignoring duplicates. Returns the number of new rows."""
    rows = [
        {"a": account_id, "v": e.vehicle_id, "ts": e.ts, "f": e.field,
         "val": json.dumps(e.value), "s": e.source}
        for e in events
    ]
    if not rows:
        return 0
    result = conn.execute(
        text("INSERT INTO telemetry_events (account_id, vehicle_id, ts, field, value, source) "
             "SELECT :a, :v, :ts, :f, CAST(:val AS jsonb), :s "
             "WHERE EXISTS (SELECT 1 FROM vehicles WHERE id = :v AND account_id = :a) "
             "ON CONFLICT (vehicle_id, ts, field) DO NOTHING"),
        rows,
    )
    return result.rowcount


def events_for_vehicle(conn: Connection, account_id: int, vehicle_id: int,
                       start: datetime, end: datetime) -> list[Event]:
    rows = conn.execute(
        text("SELECT vehicle_id, ts, field, value, source FROM telemetry_events "
             "WHERE account_id = :a AND vehicle_id = :v AND ts >= :s AND ts < :e "
             "ORDER BY ts, field"),
        {"a": account_id, "v": vehicle_id, "s": start, "e": end},
    ).all()
    return [Event(r.vehicle_id, r.ts, r.field, r.value, r.source) for r in rows]


def record_connectivity(conn: Connection, account_id: int, vehicle_id: int, ts: datetime,
                        connected: bool) -> None:
    conn.execute(
        text("INSERT INTO connectivity_events (account_id, vehicle_id, ts, connected) "
             "SELECT :a, :v, :ts, :c "
             "WHERE EXISTS (SELECT 1 FROM vehicles WHERE id = :v AND account_id = :a) "
             "ON CONFLICT DO NOTHING"),
        {"a": account_id, "v": vehicle_id, "ts": ts, "c": connected},
    )


def add_usage(conn: Connection, account_id: int, vehicle_id: int, day: date, category: str,
              count: int, field: str = "") -> None:
    conn.execute(
        text("INSERT INTO api_usage (account_id, vehicle_id, day, category, field, count) "
             "VALUES (:a, :v, :d, :c, :f, :n) "
             "ON CONFLICT (vehicle_id, day, category, field) "
             "DO UPDATE SET count = api_usage.count + EXCLUDED.count"),
        {"a": account_id, "v": vehicle_id, "d": day, "c": category, "f": field, "n": count},
    )


def ensure_month_partition(conn: Connection, month_start: date) -> str:
    """Create the telemetry_events partition for a month if missing. Returns its name."""
    if month_start.day != 1:
        raise ValueError("month_start must be the first day of a month")
    nxt = date(month_start.year + (month_start.month == 12), month_start.month % 12 + 1, 1)
    name = f"telemetry_events_{month_start:%Y_%m}"
    exists = conn.execute(text("SELECT to_regclass(:n)"), {"n": name}).scalar()
    if exists:
        return name
    # Rows already sitting in the default partition for this month must move first,
    # or Postgres refuses to attach the new partition.
    conn.execute(text(f"CREATE TABLE {name} (LIKE telemetry_events INCLUDING DEFAULTS)"))
    conn.execute(text(
        f"WITH moved AS (DELETE FROM telemetry_events_default "
        f"WHERE ts >= :s AND ts < :e RETURNING *) INSERT INTO {name} SELECT * FROM moved"),
        {"s": month_start, "e": nxt})
    conn.execute(text(
        f"ALTER TABLE telemetry_events ATTACH PARTITION {name} "
        f"FOR VALUES FROM ('{month_start.isoformat()}') TO ('{nxt.isoformat()}')"))
    return name
