"""The only query path into the database.

Every function takes an account_id and filters by it. When row-level security is
enabled at the sharing gate, this module is where the session variable gets set;
feature code does not change.
"""

import json
from collections.abc import Iterable
from datetime import date, datetime, timedelta

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


def _coords(loc):
    if not loc:
        return None, None
    return loc.get("latitude"), loc.get("longitude")


def replace_sessions(conn: Connection, account_id: int, vehicle_id: int, start: datetime,
                     end: datetime, sessions, source: str, builder_version: int,
                     places=None) -> int:
    """Replace a vehicle's sessions that start within [start, end) with `sessions`.

    Runs inside the caller's transaction, so readers never see a half-rebuilt window.
    Sessions are tagged with the nearest matching place at their start and end.
    """
    from teslai.places import match_place

    places = places or []
    owned = conn.execute(
        text("SELECT 1 FROM vehicles WHERE id = :v AND account_id = :a"),
        {"v": vehicle_id, "a": account_id},
    ).scalar_one_or_none()
    if owned is None:
        raise TeslaiError("TSL-VIN-REJECTED", f"vehicle id {vehicle_id} not in account")
    conn.execute(
        text("DELETE FROM sessions WHERE account_id = :a AND vehicle_id = :v "
             "AND start_ts >= :s AND start_ts < :e"),
        {"a": account_id, "v": vehicle_id, "s": start, "e": end},
    )
    rows = []
    for s in sessions:
        if not start <= s.start < end:
            continue
        sp, ep = match_place(s.start_location, places), match_place(s.end_location, places)
        slat, slon = _coords(s.start_location)
        elat, elon = _coords(s.end_location)
        rows.append({
            "a": account_id, "v": vehicle_id, "k": s.kind, "st": s.start, "et": s.end,
            "so": s.start_odometer, "eo": s.end_odometer, "sb": s.start_battery,
            "eb": s.end_battery, "kwh": s.energy_added_kwh, "ch": s.charger,
            "fl": sorted(s.flags), "src": source, "bv": builder_version,
            "slat": slat, "slon": slon, "elat": elat, "elon": elon,
            "sp": sp.id if sp else None, "ep": ep.id if ep else None,
            "rr": s.end_rated_range})
    if rows:
        conn.execute(
            text("INSERT INTO sessions (account_id, vehicle_id, kind, start_ts, end_ts, "
                 "start_odometer, end_odometer, start_battery, end_battery, energy_added_kwh, "
                 "charger, flags, source, builder_version, start_latitude, start_longitude, "
                 "end_latitude, end_longitude, start_place_id, end_place_id, end_rated_range) "
                 "VALUES (:a, :v, :k, :st, :et, :so, :eo, :sb, :eb, :kwh, :ch, :fl, :src, :bv, "
                 ":slat, :slon, :elat, :elon, :sp, :ep, :rr)"),
            rows,
        )
    return len(rows)


def upsert_places(conn: Connection, account_id: int, places) -> int:
    for p in places:
        conn.execute(text(
            "INSERT INTO places (account_id, name, kind, latitude, longitude, radius_m) "
            "VALUES (:a, :n, :k, :lat, :lon, :r) ON CONFLICT (account_id, name) DO UPDATE SET "
            "kind = EXCLUDED.kind, latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude, "
            "radius_m = EXCLUDED.radius_m"),
            {"a": account_id, "n": p.name, "k": p.kind, "lat": p.latitude, "lon": p.longitude,
             "r": p.radius_m})
    return len(places)


def list_places(conn: Connection, account_id: int):
    from teslai.places import Place

    rows = conn.execute(text("SELECT id, name, kind, latitude, longitude, radius_m FROM places "
                             "WHERE account_id = :a ORDER BY name"), {"a": account_id}).all()
    return [Place(r.name, r.kind, r.latitude, r.longitude, r.radius_m, r.id) for r in rows]


def retag_sessions(conn: Connection, account_id: int) -> int:
    """Re-match every session's start and end coordinates against current places."""
    from teslai.places import match_place

    places = list_places(conn, account_id)
    rows = conn.execute(text("SELECT id, start_latitude, start_longitude, end_latitude, end_longitude "
                             "FROM sessions WHERE account_id = :a"), {"a": account_id}).all()
    changed = 0
    for r in rows:
        sp = match_place({"latitude": r.start_latitude, "longitude": r.start_longitude}, places)
        ep = match_place({"latitude": r.end_latitude, "longitude": r.end_longitude}, places)
        res = conn.execute(text(
            "UPDATE sessions SET start_place_id = :sp, end_place_id = :ep WHERE id = :i "
            "AND (start_place_id IS DISTINCT FROM :sp OR end_place_id IS DISTINCT FROM :ep)"),
            {"sp": sp.id if sp else None, "ep": ep.id if ep else None, "i": r.id})
        changed += res.rowcount
    return changed


_SESSION_SELECT = (
    "SELECT s.id, s.kind, s.start_ts, s.end_ts, s.start_odometer, s.end_odometer, s.start_battery, "
    "s.end_battery, s.energy_added_kwh, s.charger, s.flags, s.builder_version, "
    "s.energy_used_kwh, s.rated_miles_used, s.avg_outside_temp, s.avg_inside_temp, s.max_speed, "
    "s.avg_speed, s.max_charger_power, "
    "sp.name AS start_place, ep.name AS end_place, sp.kind AS start_place_kind, "
    "ep.kind AS end_place_kind, sc.total_due AS invoice_total, sc.currency AS invoice_currency, "
    "sc.site_name AS supercharger_site FROM sessions s "
    "LEFT JOIN places sp ON sp.id = s.start_place_id "
    "LEFT JOIN places ep ON ep.id = s.end_place_id "
    "LEFT JOIN supercharger_sessions sc ON sc.matched_session_id = s.id "
    "WHERE s.account_id = :a AND s.vehicle_id = :v ")

SAMPLE_COLUMNS = {"latitude", "longitude", "speed", "power", "battery_level", "rated_range", "odometer",
                  "energy_remaining", "inside_temp", "outside_temp", "charger_power", "charge_energy_added",
                  "charge_state", "gear", "tpms_fl", "tpms_fr", "tpms_rl", "tpms_rr", "version", "locked",
                  "charge_limit"}


def sessions_between(conn: Connection, account_id: int, vehicle_id: int, start: datetime,
                     end: datetime, kind: str | None = None) -> list[dict]:
    q = _SESSION_SELECT + "AND s.start_ts >= :s AND s.start_ts < :e"
    params = {"a": account_id, "v": vehicle_id, "s": start, "e": end}
    if kind:
        q += " AND s.kind = :k"
        params["k"] = kind
    return [dict(r._mapping) for r in conn.execute(text(q + " ORDER BY s.start_ts"), params)]


def sessions_overlapping(conn: Connection, account_id: int, vehicle_id: int, start: datetime,
                         end: datetime) -> list[dict]:
    """Sessions that overlap [start, end), including ones still open."""
    rows = conn.execute(
        text(_SESSION_SELECT + "AND s.start_ts < :e AND (s.end_ts IS NULL OR s.end_ts > :s) "
             "ORDER BY s.start_ts"),
        {"a": account_id, "v": vehicle_id, "s": start, "e": end},
    )
    return [dict(r._mapping) for r in rows]


def session_by_id(conn: Connection, account_id: int, vehicle_id: int, session_id: int) -> dict | None:
    row = conn.execute(text(_SESSION_SELECT + "AND s.id = :id"),
                       {"a": account_id, "v": vehicle_id, "id": session_id}).first()
    return dict(row._mapping) if row else None


def latest_session(conn: Connection, account_id: int, vehicle_id: int) -> dict | None:
    row = conn.execute(text(_SESSION_SELECT + "ORDER BY s.start_ts DESC LIMIT 1"),
                       {"a": account_id, "v": vehicle_id}).first()
    return dict(row._mapping) if row else None


def adjacent_session_ids(conn: Connection, account_id: int, vehicle_id: int, kind: str,
                         start_ts: datetime) -> tuple[int | None, int | None]:
    params = {"a": account_id, "v": vehicle_id, "k": kind, "t": start_ts}
    base = "SELECT id FROM sessions WHERE account_id = :a AND vehicle_id = :v AND kind = :k "
    prev = conn.execute(text(base + "AND start_ts < :t ORDER BY start_ts DESC LIMIT 1"), params).scalar()
    nxt = conn.execute(text(base + "AND start_ts > :t ORDER BY start_ts LIMIT 1"), params).scalar()
    return prev, nxt


def _checked(columns: list[str]) -> list[str]:
    bad = set(columns) - SAMPLE_COLUMNS
    if bad:
        raise ValueError(f"unknown sample columns: {sorted(bad)}")
    return columns


def samples_between(conn: Connection, account_id: int, vehicle_id: int, start: datetime, end: datetime,
                    columns: list[str], require: str | None = None) -> list[dict]:
    cols = _checked(columns)
    q = (f"SELECT ts, {', '.join(cols)} FROM samples WHERE account_id = :a AND vehicle_id = :v "
         "AND ts >= :s AND ts <= :e")
    if require:
        q += f" AND {_checked([require])[0]} IS NOT NULL"
    rows = conn.execute(text(q + " ORDER BY ts"), {"a": account_id, "v": vehicle_id, "s": start, "e": end})
    return [dict(r._mapping) for r in rows]


def latest_samples(conn: Connection, account_id: int, vehicle_id: int, columns: list[str]) -> dict:
    """The newest non-null value of each column, plus the newest sample time as last_seen."""
    parts = ["(SELECT max(ts) FROM samples WHERE account_id = :a AND vehicle_id = :v) AS last_seen"]
    parts += [f"(SELECT {c} FROM samples WHERE account_id = :a AND vehicle_id = :v AND {c} IS NOT NULL "
              f"ORDER BY ts DESC LIMIT 1) AS {c}" for c in _checked(columns)]
    return dict(conn.execute(text("SELECT " + ", ".join(parts)), {"a": account_id, "v": vehicle_id}).one()._mapping)


def daily_tires(conn: Connection, account_id: int, vehicle_id: int, tz: str, start: datetime,
                end: datetime) -> list[dict]:
    rows = conn.execute(text(
        "SELECT (ts AT TIME ZONE :tz)::date AS day, avg(tpms_fl) AS fl, avg(tpms_fr) AS fr, "
        "avg(tpms_rl) AS rl, avg(tpms_rr) AS rr, avg(outside_temp) AS outside_temp FROM samples "
        "WHERE account_id = :a AND vehicle_id = :v AND ts >= :s AND ts < :e AND tpms_fl IS NOT NULL "
        "GROUP BY 1 ORDER BY 1"), {"a": account_id, "v": vehicle_id, "tz": tz, "s": start, "e": end})
    return [dict(r._mapping) for r in rows]


def charge_range_points(conn: Connection, account_id: int, vehicle_id: int) -> list[dict]:
    rows = conn.execute(text(
        "SELECT end_ts, end_battery, end_rated_range FROM sessions WHERE account_id = :a "
        "AND vehicle_id = :v AND kind = 'charge' AND end_ts IS NOT NULL "
        "AND end_rated_range IS NOT NULL ORDER BY end_ts"), {"a": account_id, "v": vehicle_id})
    return [dict(r._mapping) for r in rows]


def store_charging_history(conn: Connection, account_id: int, vehicle_id: int, records) -> dict[str, int]:
    """Upsert Tesla charging history records and link each to the overlapping local charge."""
    import json as _json

    from teslai.tesla.charging_history import best_match

    stored = matched = 0
    for r in records:
        charges = conn.execute(text(
            "SELECT id, start_ts, end_ts FROM sessions WHERE account_id = :a AND vehicle_id = :v "
            "AND kind = 'charge' AND start_ts < :e AND (end_ts IS NULL OR end_ts > :s)"),
            {"a": account_id, "v": vehicle_id, "s": r.start_ts - timedelta(hours=1),
             "e": (r.stop_ts or r.start_ts) + timedelta(hours=1)}).all()
        match = best_match(r, [dict(c._mapping) for c in charges])
        conn.execute(text("""
            INSERT INTO supercharger_sessions (account_id, vehicle_id, tesla_session_id, site_name, start_ts,
                stop_ts, currency, total_due, invoice_content_ids, matched_session_id, raw)
            VALUES (:a, :v, :sid, :site, :st, :sp, :cur, :tot, :inv, :m, CAST(:raw AS jsonb))
            ON CONFLICT (vehicle_id, tesla_session_id) DO UPDATE SET site_name = EXCLUDED.site_name,
                stop_ts = EXCLUDED.stop_ts, currency = EXCLUDED.currency, total_due = EXCLUDED.total_due,
                invoice_content_ids = EXCLUDED.invoice_content_ids,
                matched_session_id = EXCLUDED.matched_session_id, raw = EXCLUDED.raw, fetched_at = now()"""),
            {"a": account_id, "v": vehicle_id, "sid": r.tesla_session_id, "site": r.site_name,
             "st": r.start_ts, "sp": r.stop_ts, "cur": r.currency, "tot": r.total_due,
             "inv": r.invoice_content_ids, "m": match, "raw": _json.dumps(r.raw)})
        stored += 1
        matched += int(match is not None)
    return {"stored": stored, "matched": matched}


def live_gate_inputs(conn: Connection, account_id: int, vehicle_id: int, start: datetime, end: datetime):
    sessions = [r for r in sessions_between(conn, account_id, vehicle_id, start, end)]
    source = conn.execute(text("SELECT count(*) FROM sessions WHERE account_id = :a AND vehicle_id = :v "
                               "AND source = 'telemetry' AND start_ts >= :s AND start_ts < :e"),
                          {"a": account_id, "v": vehicle_id, "s": start, "e": end}).scalar()
    connectivity = [(r.ts, r.connected) for r in conn.execute(text(
        "SELECT ts, connected FROM connectivity_events WHERE account_id = :a AND vehicle_id = :v "
        "AND ts >= :s AND ts < :e ORDER BY ts"), {"a": account_id, "v": vehicle_id, "s": start, "e": end})]
    event_times = conn.execute(text(
        "SELECT DISTINCT ts FROM telemetry_events WHERE account_id = :a AND vehicle_id = :v "
        "AND ts >= :s AND ts < :e ORDER BY ts"), {"a": account_id, "v": vehicle_id, "s": start, "e": end}
    ).scalars().all()
    history_synced = bool(conn.execute(text(
        "SELECT 1 FROM supercharger_sessions WHERE account_id = :a AND vehicle_id = :v LIMIT 1"),
        {"a": account_id, "v": vehicle_id}).scalar())
    return sessions, int(source), connectivity, list(event_times), history_synced
