"""One notice per finished drive or charge, like TeslaFi's drive and charge emails.

Only sessions built from live telemetry that ended within the lookback are
considered, so importing years of TeslaFi history never floods notifications.
Each notice is keyed by vehicle, kind and start time in rule_firings, so it is
sent once.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from teslai.alerts import Condition
from teslai.days import _session_json

LOOKBACK = timedelta(hours=24)


def _clock(iso: str | None) -> str:
    if not iso:
        return "now"
    return datetime.fromisoformat(iso).strftime("%-I:%M %p")


def describe(r: dict, tz: ZoneInfo, tariffs=None) -> str:
    j = _session_json(r, tz, tariffs)
    when = f"{_clock(j['start'])}–{_clock(j['end'])}"
    day = datetime.fromisoformat(j["start"]).strftime("%a %b %-d")
    battery = ""
    if j["start_battery"] is not None and j["end_battery"] is not None:
        battery = f", battery {j['start_battery']:.0f}% → {j['end_battery']:.0f}%"
    if j["kind"] == "drive":
        route = ""
        if j["start_place"] or j["end_place"]:
            route = f", {j['start_place'] or 'unlabeled'} → {j['end_place'] or 'unlabeled'}"
        return f"Drive {day} {when}{route}, {j['distance_miles'] or 0:.1f} mi{battery}"
    place = f" at {j['end_place']}" if j["end_place"] else ""
    cost = f", {j['cost']:.2f}" if j["cost"] is not None else ""
    charger = f" {j['charger'].upper()}" if j["charger"] else ""
    return f"Charge {day} {when}{place}, {j['energy_added_kwh'] or 0:.1f} kWh{charger}{cost}{battery}"


def recently_finished(conn, account_id: int, now: datetime, lookback: timedelta = LOOKBACK) -> list[dict]:
    rows = conn.execute(text("""
        SELECT s.vehicle_id, v.timezone, s.kind, s.start_ts, s.end_ts, s.start_odometer, s.end_odometer,
               s.start_battery, s.end_battery, s.energy_added_kwh, s.charger, s.flags,
               sp.name AS start_place, ep.name AS end_place, sp.kind AS start_place_kind,
               ep.kind AS end_place_kind
        FROM sessions s JOIN vehicles v ON v.id = s.vehicle_id
        LEFT JOIN places sp ON sp.id = s.start_place_id
        LEFT JOIN places ep ON ep.id = s.end_place_id
        WHERE s.account_id = :a AND s.source = 'telemetry' AND s.kind IN ('drive', 'charge')
          AND s.end_ts IS NOT NULL AND s.end_ts > :since AND s.end_ts <= :now
        ORDER BY s.end_ts"""), {"a": account_id, "since": now - lookback, "now": now})
    return [dict(r._mapping) for r in rows]


def summary_conditions(rows: list[dict], cfg, tariffs=None) -> list[Condition]:
    out = []
    for r in rows:
        tz = ZoneInfo(r["timezone"])
        if r["kind"] == "drive":
            if "short" in (r.get("flags") or []):
                continue
            miles = (r["end_odometer"] or 0) - (r["start_odometer"] or 0)
            if r["start_odometer"] is None or miles < cfg.summary_drive_min_miles:
                continue
        elif (r["energy_added_kwh"] or 0) < cfg.summary_charge_min_kwh:
            continue
        out.append(Condition("session_summary",
                             f"{r['vehicle_id']}:{r['kind']}:{r['start_ts'].isoformat()}",
                             "TSL-SESSION-SUMMARY", describe(r, tz, tariffs), informational=True))
    return out
