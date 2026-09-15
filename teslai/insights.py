"""Derived views for the web app, computed from session JSON (teslai.days) and samples.

Every function here is pure: the API layer loads rows, these shape them.
Temperatures stay Celsius and tire pressures stay bar; the browser converts for display.
"""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta


def _counted_drive(s: dict) -> bool:
    return s["kind"] == "drive" and "short" not in s["flags"]


def aggregate(sessions: list[dict], key_len: int) -> dict[str, dict]:
    """Totals keyed by the first key_len characters of each session's local start (10 = day, 7 = month)."""
    out: dict[str, dict] = defaultdict(lambda: {
        "drives": 0, "miles": 0.0, "kwh_used": 0.0, "charges": 0, "kwh_added": 0.0, "charge_cost": 0.0,
        "drive_seconds": 0.0, "_temp_weight": 0.0, "_temp_sum": 0.0, "_eff_miles": 0.0, "_eff_kwh": 0.0,
        "sleep_seconds": 0.0, "idle_seconds": 0.0, "parked_drain_pct": 0.0})
    for s in sessions:
        bucket = out[s["start"][:key_len]]
        if _counted_drive(s):
            bucket["drives"] += 1
            bucket["miles"] += s["distance_miles"] or 0
            bucket["kwh_used"] += s["energy_used_kwh"] or 0
            bucket["drive_seconds"] += s["duration_s"] or 0
            if s["energy_used_kwh"] and s["distance_miles"]:
                bucket["_eff_miles"] += s["distance_miles"]
                bucket["_eff_kwh"] += s["energy_used_kwh"]
            if s["avg_outside_temp_c"] is not None and s["duration_s"]:
                bucket["_temp_sum"] += s["avg_outside_temp_c"] * s["duration_s"]
                bucket["_temp_weight"] += s["duration_s"]
        elif s["kind"] == "charge":
            bucket["charges"] += 1
            bucket["kwh_added"] += s["energy_added_kwh"] or 0
            bucket["charge_cost"] += s["cost"] or 0
        elif s["kind"] in ("sleep", "idle"):
            bucket[f"{s['kind']}_seconds"] += s["duration_s"] or 0
            if s["start_battery"] is not None and s["end_battery"] is not None:
                bucket["parked_drain_pct"] += max(0.0, s["start_battery"] - s["end_battery"])
    return {k: _finish(v) for k, v in out.items()}


def _finish(b: dict) -> dict:
    result = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in b.items() if not k.startswith("_")}
    result["wh_per_mile"] = round(b["_eff_kwh"] * 1000 / b["_eff_miles"], 1) if b["_eff_miles"] >= 0.5 else None
    result["avg_outside_temp_c"] = round(b["_temp_sum"] / b["_temp_weight"], 1) if b["_temp_weight"] else None
    return result


def calendar(sessions: list[dict], first: date, last: date) -> dict:
    by_day = aggregate(sessions, 10)
    blank = {"drives": 0, "miles": 0.0, "kwh_used": 0.0, "charges": 0, "kwh_added": 0.0, "charge_cost": 0.0,
             "drive_seconds": 0.0, "sleep_seconds": 0.0, "idle_seconds": 0.0, "parked_drain_pct": 0.0,
             "wh_per_mile": None, "avg_outside_temp_c": None}
    days = []
    d = first
    while d <= last:
        days.append({"date": d.isoformat(), **by_day.get(d.isoformat(), blank)})
        d += timedelta(days=1)
    summary = {k: sum(x[k] for x in days) for k in
               ("drives", "miles", "kwh_used", "charges", "kwh_added", "charge_cost", "drive_seconds")}
    summary = {k: round(v, 2) if isinstance(v, float) else v for k, v in summary.items()}
    total_all = aggregate([dict(s, start="all") for s in sessions], 3).get("all")
    summary["wh_per_mile"] = total_all["wh_per_mile"] if total_all else None
    summary["avg_outside_temp_c"] = total_all["avg_outside_temp_c"] if total_all else None
    summary["days_driven"] = sum(1 for x in days if x["drives"])
    return {"days": days, "summary": summary}


def efficiency(sessions: list[dict], temp_step_f: int = 10, speed_step: int = 10) -> dict:
    temps: dict[int, list[float]] = defaultdict(lambda: [0, 0.0, 0.0])
    speeds: dict[int, list[float]] = defaultdict(lambda: [0, 0.0, 0.0])
    for s in sessions:
        if not _counted_drive(s) or not s["energy_used_kwh"] or not s["distance_miles"] or s["distance_miles"] < 1:
            continue
        if s["avg_outside_temp_c"] is not None:
            f = s["avg_outside_temp_c"] * 9 / 5 + 32
            b = temps[int(math.floor(f / temp_step_f) * temp_step_f)]
            b[0] += 1
            b[1] += s["distance_miles"]
            b[2] += s["energy_used_kwh"]
        if s["avg_speed"]:
            b = speeds[int(math.floor(s["avg_speed"] / speed_step) * speed_step)]
            b[0] += 1
            b[1] += s["distance_miles"]
            b[2] += s["energy_used_kwh"]

    def rows(buckets, key, step):
        return [{key: k, f"{key}_to": k + step, "drives": v[0], "miles": round(v[1], 1),
                 "wh_per_mile": round(v[2] * 1000 / v[1], 1)} for k, v in sorted(buckets.items())]

    return {"temperature": rows(temps, "temp_f", temp_step_f), "speed": rows(speeds, "speed_mph", speed_step)}


def charge_locations(sessions: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for s in sessions:
        if s["kind"] != "charge":
            continue
        name = s["end_place"] or s["start_place"] or ("Unnamed Supercharger" if s["charger"] == "dc"
                                                      else "Unnamed location")
        g = groups.setdefault(name, {"location": name, "charges": 0, "kwh_added": 0.0, "cost": 0.0,
                                     "max_power_kw": None, "last_charge": None, "chargers": set(),
                                     "charge_seconds": 0.0})
        g["charges"] += 1
        g["kwh_added"] += s["energy_added_kwh"] or 0
        g["cost"] += s["cost"] or 0
        g["charge_seconds"] += s["duration_s"] or 0
        if s["max_charger_power"] is not None:
            g["max_power_kw"] = max(g["max_power_kw"] or 0, s["max_charger_power"])
        g["last_charge"] = max(g["last_charge"] or s["start"], s["start"])
        if s["charger"]:
            g["chargers"].add(s["charger"])
    out = []
    for g in groups.values():
        kwh = g["kwh_added"]
        out.append({**g, "kwh_added": round(kwh, 2), "cost": round(g["cost"], 2),
                    "cost_per_kwh": round(g["cost"] / kwh, 3) if kwh else None, "chargers": sorted(g["chargers"])})
    return sorted(out, key=lambda g: g["kwh_added"], reverse=True)


def tracks(drives: list[dict], samples: list[dict], max_points: int = 60) -> list[dict]:
    """Group located samples into drive polylines, thinned to at most max_points each.

    drives need id, start_ts and end_ts (datetimes); samples need ts, latitude, longitude, sorted by ts.
    Coordinates are [longitude, latitude] for map libraries.
    """
    out, i = [], 0
    for d in sorted(drives, key=lambda d: d["start_ts"]):
        end: datetime = d["end_ts"] or d["start_ts"]
        while i < len(samples) and samples[i]["ts"] < d["start_ts"]:
            i += 1
        points = []
        j = i
        while j < len(samples) and samples[j]["ts"] <= end:
            points.append([round(samples[j]["longitude"], 5), round(samples[j]["latitude"], 5)])
            j += 1
        i = j
        if len(points) < 2:
            continue
        step = max(1, math.ceil(len(points) / max_points))
        thinned = points[::step]
        if thinned[-1] != points[-1]:
            thinned.append(points[-1])
        out.append({"id": d["id"], "start": d["start_ts"].isoformat(), "points": thinned})
    return out


def thin(rows: list[dict], max_points: int) -> list[dict]:
    if len(rows) <= max_points:
        return rows
    step = math.ceil(len(rows) / max_points)
    kept = rows[::step]
    if kept[-1] is not rows[-1]:
        kept.append(rows[-1])
    return kept
