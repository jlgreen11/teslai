"""Web app endpoints: status, session lists and details, day timeline, calendar, efficiency,
charge locations, tires and the lifetime map.

Everything sits behind the owner login (see teslai.api.app). Location data is served
here because the app shows the owner's own routes and places.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import text

from teslai import insights
from teslai.costs import load_tariffs
from teslai.days import _session_json, day_window, summarize_day
from teslai.db import repo

KINDS = {"drive", "charge", "idle", "sleep", "unreachable"}
STATE_BY_KIND = {"drive": "driving", "charge": "charging", "idle": "parked", "sleep": "asleep",
                 "unreachable": "offline"}
LIVE_WINDOW = timedelta(minutes=15)
SERIES = ["latitude", "longitude", "speed", "power", "battery_level", "rated_range", "inside_temp",
          "outside_temp", "charger_power", "charge_energy_added"]


def _sample_json(r: dict, tz: ZoneInfo) -> dict:
    return {"ts": r["ts"].astimezone(tz).isoformat(), "lat": r.get("latitude"), "lon": r.get("longitude"),
            "speed": r.get("speed"), "power": r.get("power"), "battery_level": r.get("battery_level"),
            "rated_range": r.get("rated_range"), "inside_temp_c": r.get("inside_temp"),
            "outside_temp_c": r.get("outside_temp"), "charger_power": r.get("charger_power"),
            "charge_energy_added": r.get("charge_energy_added")}


def register(app: FastAPI, eng, account, vehicle) -> None:
    def local_range(conn, vehicle_id: int, start: date | None, end: date | None, default_days: int):
        a = account(conn)
        vid, tz = vehicle(conn, a, vehicle_id)
        end = end or datetime.now(UTC).astimezone(tz).date()
        start = start or end - timedelta(days=default_days - 1)
        if end < start:
            raise HTTPException(422, "end must not be before start")
        if (end - start).days > 3660:
            raise HTTPException(422, "range is limited to 10 years")
        return a, vid, tz, day_window(start, tz)[0], day_window(end, tz)[1], start, end

    def as_json(rows: list[dict], tz: ZoneInfo) -> list[dict]:
        tariffs = load_tariffs()
        return [_session_json(r, tz, tariffs) for r in rows]

    @app.get("/api/v1/vehicles/{vehicle_id}/status")
    def status(vehicle_id: int):
        with eng().connect() as conn:
            a = account(conn)
            vid, tz = vehicle(conn, a, vehicle_id)
            car = conn.execute(text("SELECT display_name, right(vin, 4) AS last4 FROM vehicles WHERE id = :v"),
                               {"v": vid}).one()
            latest = repo.latest_samples(conn, a, vid, [
                "battery_level", "rated_range", "energy_remaining", "odometer", "inside_temp", "outside_temp",
                "tpms_fl", "tpms_fr", "tpms_rl", "tpms_rr", "version", "locked", "charge_limit",
                "charger_power", "charge_energy_added"])
            session = repo.latest_session(conn, a, vid)
        now = datetime.now(UTC)
        state, since, place = "unknown", None, None
        if session:
            kind = session["kind"]
            if session["end_ts"] is None or now - session["end_ts"] < LIVE_WINDOW:
                state, since = STATE_BY_KIND[kind], session["start_ts"]
            elif kind == "sleep":
                state, since = "asleep", session["start_ts"]
            else:
                state, since = "offline", session["end_ts"]
            if kind != "drive":
                place = session["end_place"] or session["start_place"] or session["supercharger_site"]
        battery, rated = latest["battery_level"], latest["rated_range"]
        return {
            "name": car.display_name or "Your Tesla", "vin_last4": car.last4, "state": state,
            "state_since": since.astimezone(tz).isoformat() if since else None,
            "battery_level": battery, "charge_limit": latest["charge_limit"],
            "energy_remaining_kwh": latest["energy_remaining"], "rated_range": rated,
            "est_100_range": round(rated / battery * 100, 1) if rated and battery else None,
            "odometer": latest["odometer"], "version": latest["version"], "fsd_miles": None,
            "miles_since_reset": None, "inside_temp_c": latest["inside_temp"],
            "outside_temp_c": latest["outside_temp"], "locked": latest["locked"], "sentry": None,
            "tpms": {"fl": latest["tpms_fl"], "fr": latest["tpms_fr"], "rl": latest["tpms_rl"],
                     "rr": latest["tpms_rr"]},
            "charging": {"power_kw": latest["charger_power"], "added_kwh": latest["charge_energy_added"]}
            if state == "charging" else None,
            "place": place,
            "last_seen": latest["last_seen"].astimezone(tz).isoformat() if latest["last_seen"] else None,
        }

    @app.get("/api/v1/vehicles/{vehicle_id}/session-list")
    def session_list(vehicle_id: int, kind: str = "drive", start: date | None = None, end: date | None = None,
                     limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
        kinds = set(kind.split(","))
        if not kinds <= KINDS:
            raise HTTPException(422, f"kind must be among {sorted(KINDS)}")
        with eng().connect() as conn:
            a, vid, tz, rs, re_, _, _ = local_range(conn, vehicle_id, start, end, 30)
            rows = [r for r in repo.sessions_between(conn, a, vid, rs, re_) if r["kind"] in kinds]
        items = as_json(rows, tz)
        items = [s for s in items if s["kind"] != "drive" or "short" not in s["flags"]]
        totals = insights.aggregate([dict(s, start="all") for s in items], 3).get("all") or {}
        totals["energy_cost"] = round(sum(s["energy_cost"] or 0 for s in items), 2)
        totals["gas_savings"] = round(sum(s["gas_savings"] or 0 for s in items), 2)
        totals["count"] = len(items)
        items.reverse()
        return {"items": items[offset:offset + limit], "total": len(items), "totals": totals}

    @app.get("/api/v1/vehicles/{vehicle_id}/session/{session_id}")
    def session_detail(vehicle_id: int, session_id: int):
        with eng().connect() as conn:
            a = account(conn)
            vid, tz = vehicle(conn, a, vehicle_id)
            row = repo.session_by_id(conn, a, vid, session_id)
            if row is None:
                raise HTTPException(404, "Session not found.")
            end = row["end_ts"] or datetime.now(UTC)
            samples = repo.samples_between(conn, a, vid, row["start_ts"], end, SERIES)
            prev_id, next_id = repo.adjacent_session_ids(conn, a, vid, row["kind"], row["start_ts"])
        return {"session": as_json([row], tz)[0], "prev_id": prev_id, "next_id": next_id,
                "samples": [_sample_json(r, tz) for r in insights.thin(samples, 1500)]}

    @app.get("/api/v1/vehicles/{vehicle_id}/timeline/{day}")
    def timeline(vehicle_id: int, day: date):
        with eng().connect() as conn:
            a = account(conn)
            vid, tz = vehicle(conn, a, vehicle_id)
            start, end = day_window(day, tz)
            rows = repo.sessions_overlapping(conn, a, vid, start, end)
            battery = repo.samples_between(conn, a, vid, start, end, ["battery_level"], require="battery_level")
            week_start = day_window(day - timedelta(days=6), tz)[0]
            week_rows = repo.sessions_between(conn, a, vid, week_start, end)
        tariffs = load_tariffs()
        summary = summarize_day(day, tz, rows, tariffs=tariffs)
        week = insights.calendar(as_json(week_rows, tz), day - timedelta(days=6), day)["days"]
        today = insights.calendar(summary.sessions, day, day)["days"][0]
        return {**summary.__dict__, "totals": today, "week": week,
                "battery": [{"ts": r["ts"].astimezone(tz).isoformat(), "battery_level": r["battery_level"]}
                            for r in insights.thin(battery, 400)]}

    @app.get("/api/v1/vehicles/{vehicle_id}/calendar/{year}/{month}")
    def calendar_month(vehicle_id: int, year: int, month: int):
        if not 1 <= month <= 12 or not 2000 <= year <= 2100:
            raise HTTPException(422, "invalid month")
        first = date(year, month, 1)
        last = (date(year + (month == 12), month % 12 + 1, 1)) - timedelta(days=1)
        with eng().connect() as conn:
            a, vid, tz, rs, re_, _, _ = local_range(conn, vehicle_id, first, last, 31)
            rows = repo.sessions_between(conn, a, vid, rs, re_)
        return {"year": year, "month": month, **insights.calendar(as_json(rows, tz), first, last)}

    @app.get("/api/v1/vehicles/{vehicle_id}/calendar/{year}")
    def calendar_year(vehicle_id: int, year: int):
        if not 2000 <= year <= 2100:
            raise HTTPException(422, "invalid year")
        with eng().connect() as conn:
            a, vid, tz, rs, re_, _, _ = local_range(conn, vehicle_id, date(year, 1, 1), date(year, 12, 31), 365)
            rows = repo.sessions_between(conn, a, vid, rs, re_)
        by_month = insights.aggregate(as_json(rows, tz), 7)
        return {"year": year, "months": [{"month": f"{year}-{m:02d}", **by_month[f"{year}-{m:02d}"]}
                                         for m in range(1, 13) if f"{year}-{m:02d}" in by_month]}

    @app.get("/api/v1/vehicles/{vehicle_id}/efficiency")
    def efficiency(vehicle_id: int, start: date | None = None, end: date | None = None):
        with eng().connect() as conn:
            a, vid, tz, rs, re_, s, e = local_range(conn, vehicle_id, start, end, 365)
            rows = repo.sessions_between(conn, a, vid, rs, re_, kind="drive")
        return {"start": s.isoformat(), "end": e.isoformat(), **insights.efficiency(as_json(rows, tz))}

    @app.get("/api/v1/vehicles/{vehicle_id}/charge-locations")
    def charge_locations(vehicle_id: int, start: date | None = None, end: date | None = None):
        with eng().connect() as conn:
            a, vid, tz, rs, re_, s, e = local_range(conn, vehicle_id, start, end, 365)
            rows = repo.sessions_between(conn, a, vid, rs, re_, kind="charge")
        return {"start": s.isoformat(), "end": e.isoformat(),
                "locations": insights.charge_locations(as_json(rows, tz))}

    @app.get("/api/v1/vehicles/{vehicle_id}/tires")
    def tires(vehicle_id: int, start: date | None = None, end: date | None = None):
        with eng().connect() as conn:
            a, vid, tz, rs, re_, s, e = local_range(conn, vehicle_id, start, end, 90)
            rows = repo.daily_tires(conn, a, vid, str(tz), rs, re_)
        return {"start": s.isoformat(), "end": e.isoformat(), "days": [
            {"date": r["day"].isoformat(), **{k: None if r[k] is None else round(float(r[k]), 3)
                                              for k in ("fl", "fr", "rl", "rr", "outside_temp")}} for r in rows]}

    @app.get("/api/v1/vehicles/{vehicle_id}/map")
    def lifetime_map(vehicle_id: int, start: date | None = None, end: date | None = None):
        with eng().connect() as conn:
            a, vid, _tz, rs, re_, s, e = local_range(conn, vehicle_id, start, end, 365)
            drives = [r for r in repo.sessions_between(conn, a, vid, rs, re_, kind="drive")
                      if "short" not in (r["flags"] or [])]
            samples = repo.samples_between(conn, a, vid, rs, re_, ["latitude", "longitude"], require="latitude")
            places = repo.list_places(conn, a)
        return {"start": s.isoformat(), "end": e.isoformat(), "tracks": insights.tracks(drives, samples),
                "places": [{"name": p.name, "kind": p.kind, "lat": p.latitude, "lon": p.longitude}
                           for p in places]}
