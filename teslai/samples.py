"""Build and store time-series samples, and derive per-session statistics.

    TeslaFi CSV row ──────────────┐
                                   ├─▶ sample dict ─▶ samples (upsert on vehicle, ts)
    live events ─▶ reducer snapshot┘
                                            │
    sessions in a window ◀─ enrich_sessions ┘  (SQL aggregates over each session's samples)

Energy used by a drive comes from energy_remaining when the car reports it, and
otherwise from the battery percentage change times the pack size.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import Connection, text

from teslai.config import default_field_specs
from teslai.reducer import Event, StateReducer

COLUMNS = ["latitude", "longitude", "speed", "power", "battery_level", "rated_range", "odometer",
           "energy_remaining", "inside_temp", "outside_temp", "charger_power", "charge_energy_added",
           "charge_state", "gear", "tpms_fl", "tpms_fr", "tpms_rl", "tpms_rr"]

FIELD_TO_COLUMN = {
    "VehicleSpeed": "speed", "DrivePower": "power", "BatteryLevel": "battery_level",
    "RatedRange": "rated_range", "Odometer": "odometer", "EnergyRemaining": "energy_remaining",
    "InsideTemp": "inside_temp", "OutsideTemp": "outside_temp", "ACChargingPower": "charger_power",
    "ChargeEnergyAdded": "charge_energy_added", "DetailedChargeState": "charge_state", "Gear": "gear",
    "TpmsPressureFl": "tpms_fl", "TpmsPressureFr": "tpms_fr", "TpmsPressureRl": "tpms_rl",
    "TpmsPressureRr": "tpms_rr",
}


def sample_from_fields(ts: datetime, fields: dict) -> dict:
    row = {c: None for c in COLUMNS}
    row["ts"] = ts
    for field, value in fields.items():
        if field == "Location" and isinstance(value, dict):
            row["latitude"], row["longitude"] = value.get("latitude"), value.get("longitude")
        elif field in FIELD_TO_COLUMN and value is not None:
            col = FIELD_TO_COLUMN[field]
            row[col] = value if col in ("charge_state", "gear") else float(value)
    if row["charger_power"] is None and fields.get("DCChargingPower") is not None:
        row["charger_power"] = float(fields["DCChargingPower"])
    if row["power"] is None and fields.get("PackVoltage") is not None and fields.get("PackCurrent") is not None:
        row["power"] = round(float(fields["PackVoltage"]) * float(fields["PackCurrent"]) / 1000, 2)
    return row


def samples_from_events(events: list[Event], min_spacing: timedelta = timedelta(seconds=10)) -> list[dict]:
    """Snapshot the car at event times, at most one per min_spacing unless gear or charge state changes."""
    reducer = StateReducer(default_field_specs())
    times = sorted({e.ts for e in events})
    by_ts: dict[datetime, list[Event]] = {}
    for e in events:
        by_ts.setdefault(e.ts, []).append(e)
    out, last_ts, last_state = [], None, None
    for ts in times:
        for e in by_ts[ts]:
            reducer.apply(e)
        snap = {name: fv.value for name, fv in reducer.snapshot(ts).items()}
        state = (snap.get("Gear"), snap.get("DetailedChargeState"))
        if last_ts is None or ts - last_ts >= min_spacing or state != last_state:
            out.append(sample_from_fields(ts, snap))
            last_ts, last_state = ts, state
    return out


def upsert_samples(conn: Connection, account_id: int, vehicle_id: int, rows: Iterable[dict],
                   source: str, batch: int = 2000) -> int:
    cols = ["account_id", "vehicle_id", "ts", "source", *COLUMNS]
    sql = text(f"INSERT INTO samples ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "
               f"ON CONFLICT (vehicle_id, ts) DO UPDATE SET "
               + ", ".join(f"{c} = COALESCE(EXCLUDED.{c}, samples.{c})" for c in COLUMNS))
    total, chunk = 0, []
    for r in rows:
        chunk.append({**r, "account_id": account_id, "vehicle_id": vehicle_id, "source": source})
        if len(chunk) >= batch:
            conn.execute(sql, chunk)
            total += len(chunk)
            chunk = []
    if chunk:
        conn.execute(sql, chunk)
        total += len(chunk)
    return total


def enrich_sessions(conn: Connection, account_id: int, vehicle_id: int, start: datetime, end: datetime,
                    pack_kwh: float = 75.0) -> None:
    conn.execute(text("""
        UPDATE sessions s SET
            avg_outside_temp = a.ot, avg_inside_temp = a.it, max_speed = a.ms, avg_speed = a.av,
            max_charger_power = a.mp,
            rated_miles_used = CASE WHEN s.kind = 'drive' THEN a.first_range - a.last_range END,
            energy_used_kwh = CASE WHEN s.kind = 'drive' THEN COALESCE(
                a.first_energy - a.last_energy,
                (s.start_battery - s.end_battery) / 100.0 * :pack) END
        FROM (
            SELECT s2.id,
                avg(x.outside_temp) AS ot, avg(x.inside_temp) AS it, max(x.speed) AS ms,
                avg(x.speed) FILTER (WHERE x.speed > 0) AS av, max(x.charger_power) AS mp,
                (array_agg(x.rated_range ORDER BY x.ts) FILTER (WHERE x.rated_range IS NOT NULL))[1] AS first_range,
                (array_agg(x.rated_range ORDER BY x.ts DESC) FILTER (WHERE x.rated_range IS NOT NULL))[1] AS last_range,
                (array_agg(x.energy_remaining ORDER BY x.ts) FILTER (WHERE x.energy_remaining IS NOT NULL))[1] AS first_energy,
                (array_agg(x.energy_remaining ORDER BY x.ts DESC) FILTER (WHERE x.energy_remaining IS NOT NULL))[1] AS last_energy
            FROM sessions s2
            JOIN samples x ON x.vehicle_id = s2.vehicle_id AND x.ts >= s2.start_ts
                AND x.ts <= COALESCE(s2.end_ts, now())
            WHERE s2.account_id = :a AND s2.vehicle_id = :v AND s2.start_ts >= :s AND s2.start_ts < :e
              AND s2.kind IN ('drive', 'charge')
            GROUP BY s2.id
        ) a
        WHERE s.id = a.id"""), {"a": account_id, "v": vehicle_id, "s": start, "e": end, "pack": pack_kwh})
    # Drives with no samples still get battery-based energy.
    conn.execute(text("""
        UPDATE sessions SET energy_used_kwh = (start_battery - end_battery) / 100.0 * :pack
        WHERE account_id = :a AND vehicle_id = :v AND kind = 'drive' AND energy_used_kwh IS NULL
          AND start_battery IS NOT NULL AND end_battery IS NOT NULL
          AND start_ts >= :s AND start_ts < :e"""),
        {"a": account_id, "v": vehicle_id, "s": start, "e": end, "pack": pack_kwh})
