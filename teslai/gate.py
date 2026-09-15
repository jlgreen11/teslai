"""History gate: compare teslai's derived sessions with TeslaFi's own numbers.

Monthly totals are computed from derived sessions and compared, month by month,
with an answer key taken from TeslaFi's history API. The gate is evaluated
separately before and after TeslaFi's switch from polling to streaming, because
sample density differs between the two eras.

Passing the gate means teslai reproduces TeslaFi's view of history. It is also
cross-checked against odometer deltas, so matching TeslaFi's own mistakes is not
enough to pass.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from teslai.builder import Session

METRICS = ("drive_count", "miles", "charge_count", "kwh_added")


@dataclass
class MonthTotals:
    drive_count: int = 0
    miles: float = 0.0
    charge_count: int = 0
    kwh_added: float = 0.0
    odometer_start: float | None = None
    odometer_end: float | None = None

    @property
    def odometer_delta(self) -> float | None:
        if self.odometer_start is None or self.odometer_end is None:
            return None
        return self.odometer_end - self.odometer_start


def month_of(ts: datetime, tz: ZoneInfo) -> str:
    return f"{ts.astimezone(tz):%Y-%m}"


def totals_from_sessions(sessions: Iterable[Session], tz: ZoneInfo,
                         include_short: bool = False) -> dict[str, MonthTotals]:
    months: dict[str, MonthTotals] = defaultdict(MonthTotals)
    for s in sorted(sessions, key=lambda s: s.start):
        if s.end is None:
            continue
        m = months[month_of(s.start, tz)]
        if s.kind == "drive":
            if "short" in s.flags and not include_short:
                continue
            m.drive_count += 1
            m.miles += s.distance or 0.0
            if s.start_odometer is not None and m.odometer_start is None:
                m.odometer_start = s.start_odometer
            if s.end_odometer is not None:
                m.odometer_end = s.end_odometer
        elif s.kind == "charge":
            m.charge_count += 1
            m.kwh_added += s.energy_added_kwh or 0.0
    return dict(months)


@dataclass
class MetricResult:
    metric: str
    ours: float
    theirs: float
    ok: bool

    @property
    def rel_diff(self) -> float:
        if self.theirs == 0:
            return 0.0 if self.ours == 0 else float("inf")
        return (self.ours - self.theirs) / self.theirs


@dataclass
class MonthResult:
    month: str
    era: str
    metrics: list[MetricResult] = field(default_factory=list)
    odometer_ok: bool | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(m.ok for m in self.metrics) and self.odometer_ok is not False


def _within(ours: float, theirs: float, rel: float, abs_tol: float) -> bool:
    return abs(ours - theirs) <= max(abs_tol, abs(theirs) * rel)


def compare(ours: dict[str, MonthTotals], theirs: dict[str, dict[str, float]],
            switch_date: date | None = None, rel_tolerance: float = 0.01,
            odometer_tolerance: float = 0.005) -> list[MonthResult]:
    results = []
    for month in sorted(set(ours) | set(theirs)):
        o = ours.get(month, MonthTotals())
        t = theirs.get(month)
        era = "all"
        if switch_date is not None:
            era = "streaming" if month >= f"{switch_date:%Y-%m}" else "polling"
        r = MonthResult(month, era)
        if t is None:
            r.notes.append("month missing from TeslaFi answer key")
            r.metrics.append(MetricResult("present_in_answer_key", 1, 0, False))
            results.append(r)
            continue
        for metric in METRICS:
            mine = float(getattr(o, metric))
            other = float(t.get(metric, 0.0))
            abs_tol = 1.0 if metric.endswith("_count") else 0.0
            r.metrics.append(MetricResult(metric, mine, other,
                                          _within(mine, other, rel_tolerance, abs_tol)))
        delta = o.odometer_delta
        if delta is not None and delta > 0:
            r.odometer_ok = _within(o.miles, delta, odometer_tolerance, 0.5)
            if not r.odometer_ok:
                r.notes.append(f"drive miles {o.miles:.1f} vs odometer delta {delta:.1f}")
        results.append(r)
    return results


def summarize(results: list[MonthResult]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"months": 0, "passed": 0})
    for r in results:
        out[r.era]["months"] += 1
        out[r.era]["passed"] += int(r.ok)
    return dict(out)


def render_table(results: list[MonthResult]) -> str:
    header = ("month    era        drives        miles              charges       kWh added"
              "          odo  result")
    lines = [header]
    for r in results:
        cells = []
        by = {m.metric: m for m in r.metrics}
        for metric in METRICS:
            m = by.get(metric)
            cells.append("-" if m is None else f"{m.ours:>7.1f}/{m.theirs:<7.1f}")
        odo = {None: "  -", True: " ok", False: "BAD"}[r.odometer_ok]
        lines.append(f"{r.month}  {r.era:<9}  " + "  ".join(cells)
                     + f"  {odo}  {'PASS' if r.ok else 'FAIL'}")
    return "\n".join(lines)
