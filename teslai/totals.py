"""Period totals and CSV export over sessions.

Totals group sessions by the local day, month or year in which they start, so a
drive at 11pm counts on that date. Short drives are excluded from drive counts and
miles, as TeslaFi does by default. Charging cost uses the same place-based
pricing as the day view.
"""

import csv
import io
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Literal
from zoneinfo import ZoneInfo

from teslai.days import _session_json

Group = Literal["day", "month", "year"]
FORMATS = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}
CSV_COLUMNS = ["kind", "start", "end", "duration_minutes", "distance_miles", "start_battery",
               "end_battery", "energy_added_kwh", "charger", "cost", "start_place", "end_place",
               "flags"]


@dataclass
class PeriodTotals:
    period: str
    drives: int = 0
    miles: float = 0.0
    drive_minutes: int = 0
    charges: int = 0
    kwh_added: float = 0.0
    charging_cost: float = 0.0


def totals(rows: list[dict], tz: ZoneInfo, group: Group, tariffs=None) -> list[dict]:
    if group not in FORMATS:
        raise ValueError(f"group must be one of {sorted(FORMATS)}")
    out: OrderedDict[str, PeriodTotals] = OrderedDict()
    for r in sorted(rows, key=lambda r: r["start_ts"]):
        if r["end_ts"] is None:
            continue
        key = r["start_ts"].astimezone(tz).strftime(FORMATS[group])
        t = out.setdefault(key, PeriodTotals(key))
        if r["kind"] == "drive" and "short" not in (r.get("flags") or []):
            t.drives += 1
            if r["start_odometer"] is not None and r["end_odometer"] is not None:
                t.miles += r["end_odometer"] - r["start_odometer"]
            t.drive_minutes += int((r["end_ts"] - r["start_ts"]).total_seconds() // 60)
        elif r["kind"] == "charge":
            t.charges += 1
            t.kwh_added += r["energy_added_kwh"] or 0.0
            t.charging_cost += _session_json(r, tz, tariffs)["cost"] or 0.0
    result = []
    for t in out.values():
        d = asdict(t)
        d["miles"], d["kwh_added"], d["charging_cost"] = (round(t.miles, 2), round(t.kwh_added, 3),
                                                          round(t.charging_cost, 2))
        result.append(d)
    return result


def sessions_csv(rows: list[dict], tz: ZoneInfo, tariffs=None) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in sorted(rows, key=lambda r: r["start_ts"]):
        j = _session_json(r, tz, tariffs)
        minutes = (int((r["end_ts"] - r["start_ts"]).total_seconds() // 60)
                   if r["end_ts"] is not None else "")
        w.writerow({
            "kind": j["kind"], "start": j["start"], "end": j["end"] or "",
            "duration_minutes": minutes,
            "distance_miles": "" if j["distance_miles"] is None else j["distance_miles"],
            "start_battery": "" if j["start_battery"] is None else j["start_battery"],
            "end_battery": "" if j["end_battery"] is None else j["end_battery"],
            "energy_added_kwh": "" if j["energy_added_kwh"] is None else j["energy_added_kwh"],
            "charger": j["charger"] or "", "cost": "" if j["cost"] is None else j["cost"],
            "start_place": j["start_place"] or "", "end_place": j["end_place"] or "",
            "flags": ";".join(j["flags"]),
        })
    return buf.getvalue()
