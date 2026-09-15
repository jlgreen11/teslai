"""Live gate: is teslai's own telemetry trustworthy enough to cancel TeslaFi?

Evaluated over a window of live-telemetry sessions (default 14 days):

    FAIL checks (block cutover)
      odometer      Σ drive miles within 0.5% of the odometer movement across all drives
      continuity    no more than 0.2 mi of movement between one drive's end and the next's start
      gaps          no stretch longer than 30 min with the car connected but no telemetry
    WARN checks (worth reading, do not block)
      energy        kWh added within 25% of battery change × pack size
      supercharger  every DC charge linked to a Tesla charging history record
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise


@dataclass
class Check:
    name: str
    severity: str  # "fail" or "warn"
    ok: bool
    summary: str
    problems: list[str] = field(default_factory=list)


@dataclass
class LiveGateParams:
    odometer_tolerance: float = 0.005
    max_unlogged_miles: float = 0.2
    max_gap: timedelta = timedelta(minutes=30)
    energy_tolerance: float = 0.25
    pack_kwh: float = 75.0


def check_odometer(drives: list[dict], p: LiveGateParams) -> Check:
    known = [d for d in drives if d["start_odometer"] is not None and d["end_odometer"] is not None]
    if not known:
        return Check("odometer", "fail", False, "no drives with odometer readings")
    miles = sum(d["end_odometer"] - d["start_odometer"] for d in known)
    moved = known[-1]["end_odometer"] - known[0]["start_odometer"]
    ok = moved <= 0 or abs(miles - moved) <= max(0.5, moved * p.odometer_tolerance)
    return Check("odometer", "fail", ok, f"drives {miles:.1f} mi vs odometer {moved:.1f} mi")


def check_continuity(drives: list[dict], p: LiveGateParams) -> Check:
    problems = []
    known = [d for d in drives if d["start_odometer"] is not None and d["end_odometer"] is not None]
    for prev, nxt in pairwise(known):
        gap = nxt["start_odometer"] - prev["end_odometer"]
        if gap > p.max_unlogged_miles:
            problems.append(f"{gap:.2f} mi unlogged between {prev['end_ts']:%Y-%m-%d %H:%M} and "
                            f"{nxt['start_ts']:%Y-%m-%d %H:%M} UTC")
    return Check("continuity", "fail", not problems,
                 "no unlogged movement" if not problems else f"{len(problems)} unlogged movements",
                 problems)


def connected_intervals(connectivity: list[tuple[datetime, bool]], end: datetime):
    """Yield (start, stop) intervals during which the car reported connected."""
    start = None
    for ts, connected in sorted(connectivity):
        if connected and start is None:
            start = ts
        elif not connected and start is not None:
            yield start, ts
            start = None
    if start is not None:
        yield start, end


def check_gaps(connectivity: list[tuple[datetime, bool]], event_times: list[datetime], end: datetime,
               p: LiveGateParams) -> Check:
    events = sorted(event_times)
    problems = []
    import bisect

    for c_start, c_stop in connected_intervals(connectivity, end):
        i = bisect.bisect_left(events, c_start)
        cursor = c_start
        while i < len(events) and events[i] <= c_stop:
            if events[i] - cursor > p.max_gap:
                problems.append(f"no telemetry {cursor:%Y-%m-%d %H:%M}–{events[i]:%H:%M} UTC while connected")
            cursor = events[i]
            i += 1
        if c_stop - cursor > p.max_gap:
            problems.append(f"no telemetry {cursor:%Y-%m-%d %H:%M}–{c_stop:%H:%M} UTC while connected")
    return Check("gaps", "fail", not problems,
                 "no telemetry gaps while connected" if not problems else f"{len(problems)} gaps", problems)


def check_energy(charges: list[dict], p: LiveGateParams) -> Check:
    problems = []
    for c in charges:
        if c["start_battery"] is None or c["end_battery"] is None or not c["energy_added_kwh"]:
            continue
        expected = (c["end_battery"] - c["start_battery"]) / 100 * p.pack_kwh
        if expected <= 1:
            continue
        diff = abs(c["energy_added_kwh"] - expected) / expected
        if diff > p.energy_tolerance:
            problems.append(f"charge at {c['start_ts']:%Y-%m-%d %H:%M} UTC added {c['energy_added_kwh']:.1f} kWh, "
                            f"battery change suggests {expected:.1f} kWh")
    return Check("energy", "warn", not problems,
                 "charge energy consistent with battery change" if not problems else f"{len(problems)} charges off",
                 problems)


def check_supercharger(charges: list[dict], history_synced: bool) -> Check:
    if not history_synced:
        return Check("supercharger", "warn", True, "charging history not synced; skipped")
    unmatched = [c for c in charges if c["charger"] == "dc" and c.get("invoice_total") is None]
    problems = [f"DC charge at {c['start_ts']:%Y-%m-%d %H:%M} UTC has no Tesla record" for c in unmatched]
    return Check("supercharger", "warn", not problems,
                 "every DC charge linked to Tesla history" if not problems else f"{len(problems)} unlinked", problems)


def evaluate(sessions: list[dict], connectivity: list[tuple[datetime, bool]], event_times: list[datetime],
             end: datetime, history_synced: bool, p: LiveGateParams | None = None) -> list[Check]:
    p = p or LiveGateParams()
    drives = sorted((s for s in sessions if s["kind"] == "drive" and s["end_ts"] is not None
                     and "short" not in (s.get("flags") or [])), key=lambda s: s["start_ts"])
    charges = [s for s in sessions if s["kind"] == "charge" and s["end_ts"] is not None]
    return [check_odometer(drives, p), check_continuity(drives, p),
            check_gaps(connectivity, event_times, end, p), check_energy(charges, p),
            check_supercharger(charges, history_synced)]


def passed(checks: list[Check]) -> bool:
    return all(c.ok for c in checks if c.severity == "fail")
