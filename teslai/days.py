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


def summarize_day(day: date, tz: ZoneInfo, rows: list[dict]) -> DaySummary:
    drives = [r for r in rows if r["kind"] == "drive" and "short" not in (r.get("flags") or [])]
    charges = [r for r in rows if r["kind"] == "charge"]
    miles = sum((r["end_odometer"] or 0) - (r["start_odometer"] or 0) for r in drives
                if r["end_odometer"] is not None and r["start_odometer"] is not None)
    return DaySummary(
        date=day.isoformat(),
        timezone=str(tz),
        drives=len(drives),
        miles=round(miles, 2),
        charges=len(charges),
        kwh_added=round(sum(r["energy_added_kwh"] or 0 for r in charges), 3),
        sessions=[_session_json(r, tz) for r in rows],
    )


def _session_json(r: dict, tz: ZoneInfo) -> dict:
    def local(ts):
        return ts.astimezone(tz).isoformat() if ts else None

    distance = None
    if r["start_odometer"] is not None and r["end_odometer"] is not None:
        distance = round(r["end_odometer"] - r["start_odometer"], 2)
    return {
        "kind": r["kind"],
        "start": local(r["start_ts"]),
        "end": local(r["end_ts"]),
        "distance_miles": distance if r["kind"] == "drive" else None,
        "start_battery": r["start_battery"],
        "end_battery": r["end_battery"],
        "energy_added_kwh": r["energy_added_kwh"],
        "charger": r["charger"],
        "flags": list(r.get("flags") or []),
    }
