"""Local-day windows and day summaries.

A "day" is the owner's local calendar day, so a drive at 11pm counts on that
date even though it is the next day in UTC. DST days are 23 or 25 hours long.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def day_window(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC start and end of a local calendar day."""
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end


@dataclass
class DaySummary:
    date: str
    timezone: str
    drives: int
    miles: float
    charges: int
    kwh_added: float
    sessions: list[dict]
    charging_cost: float = 0.0
    currency: str = "USD"


def summarize_day(day: date, tz: ZoneInfo, rows: list[dict], tariffs=None) -> DaySummary:
    drives = [r for r in rows if r["kind"] == "drive" and "short" not in (r.get("flags") or [])]
    charges = [r for r in rows if r["kind"] == "charge"]
    miles = sum((r["end_odometer"] or 0) - (r["start_odometer"] or 0) for r in drives
                if r["end_odometer"] is not None and r["start_odometer"] is not None)
    sessions = [_session_json(r, tz, tariffs) for r in rows]
    return DaySummary(
        date=day.isoformat(),
        timezone=str(tz),
        drives=len(drives),
        miles=round(miles, 2),
        charges=len(charges),
        kwh_added=round(sum(r["energy_added_kwh"] or 0 for r in charges), 3),
        sessions=sessions,
        charging_cost=round(sum(x["cost"] or 0 for x in sessions if x["kind"] == "charge"), 2),
        currency=tariffs.currency if tariffs else "USD",
    )


def _price_kind(r: dict) -> str:
    kind = r.get("end_place_kind") or r.get("start_place_kind")
    if r.get("charger") == "dc" and kind != "free":
        return "supercharger"
    return {"home": "home", "free": "free", "supercharger": "supercharger"}.get(kind, "public")


def _session_json(r: dict, tz: ZoneInfo, tariffs=None) -> dict:
    def local(ts):
        return ts.astimezone(tz).isoformat() if ts else None

    distance = None
    if r["start_odometer"] is not None and r["end_odometer"] is not None:
        distance = round(r["end_odometer"] - r["start_odometer"], 2)
    drive = r["kind"] == "drive"
    duration = (r["end_ts"] - r["start_ts"]).total_seconds() if r["end_ts"] else None
    used = r.get("energy_used_kwh")
    rated = r.get("rated_miles_used")
    wh_per_mile = round(used * 1000 / distance, 1) if drive and used and distance and distance >= 0.1 else None
    efficiency = round(distance / rated * 100, 1) if drive and rated and rated >= 0.1 and distance else None
    energy_cost = round(used * tariffs.home_default, 2) if tariffs and drive and used else None
    savings = None
    if tariffs and drive and distance and energy_cost is not None and tariffs.gas_mpg > 0:
        from teslai.costs import gas_savings

        savings = gas_savings(distance, energy_cost, tariffs)
    return {
        "id": r.get("id"),
        "duration_s": duration,
        "energy_used_kwh": round(used, 2) if used is not None else None,
        "rated_miles_used": round(rated, 1) if rated is not None and drive else None,
        "wh_per_mile": wh_per_mile,
        "efficiency_pct": efficiency,
        "energy_cost": energy_cost,
        "gas_savings": savings,
        "avg_outside_temp_c": _round(r.get("avg_outside_temp"), 1),
        "avg_inside_temp_c": _round(r.get("avg_inside_temp"), 1),
        "max_speed": _round(r.get("max_speed"), 0),
        "avg_speed": _round(r.get("avg_speed"), 0),
        "max_charger_power": _round(r.get("max_charger_power"), 1),
        "start_odometer": _round(r.get("start_odometer"), 1),
        "end_odometer": _round(r.get("end_odometer"), 1),
        "kind": r["kind"],
        "start": local(r["start_ts"]),
        "end": local(r["end_ts"]),
        "distance_miles": distance if r["kind"] == "drive" else None,
        "start_battery": r["start_battery"],
        "end_battery": r["end_battery"],
        "energy_added_kwh": r["energy_added_kwh"],
        "charger": r["charger"],
        "flags": list(r.get("flags") or []),
        "start_place": r.get("start_place"),
        "end_place": r.get("end_place") or r.get("supercharger_site"),
        "cost_source": "invoice" if r.get("invoice_total") is not None else (
            "estimate" if r["kind"] == "charge" else None),
        "cost": _cost(r, tz, tariffs),
    }


def _round(value, digits: int):
    return None if value is None else round(float(value), digits)


def _cost(r: dict, tz: ZoneInfo, tariffs) -> float | None:
    if tariffs is None or r["kind"] != "charge" or r["end_ts"] is None:
        return None
    from teslai.costs import charge_cost

    invoice = r.get("invoice_total")
    return charge_cost(r["start_ts"], r["end_ts"], r["energy_added_kwh"] or 0.0, _price_kind(r),
                       tz, tariffs, invoice_total=None if invoice is None else float(invoice))
