import itertools
from datetime import date

from teslai.builder import build_sessions
from teslai.demo import generate
from teslai.importer.teslafi import to_events


def test_demo_generates_plausible_week():
    rows, places = generate(days=14, end=date(2026, 6, 14))
    assert len(rows) > 1000 and len(places) == 6
    assert all(a.ts <= b.ts for a, b in itertools.pairwise(rows))
    events, conn = to_events(rows, 1)
    sessions = build_sessions(events, conn, until=rows[-1].ts)
    kinds = [s.kind for s in sessions]
    drives = [s for s in sessions if s.kind == "drive" and "short" not in s.flags]
    assert len(drives) >= 20 and kinds.count("charge") >= 3 and "sleep" in kinds
    miles = sum(d.distance for d in drives)
    assert 150 < miles < 2000
    assert all(0 < r.fields["BatteryLevel"] <= 100 for r in rows)


def test_demo_drives_split_at_stops_and_charges_are_whole():
    rows, _ = generate(days=60, end=date(2026, 7, 31))
    events, conn = to_events(rows, 1)
    sessions = build_sessions(events, conn, until=rows[-1].ts)
    drives = [s for s in sessions if s.kind == "drive" and "short" not in s.flags]
    # Local legs are short; only highway road-trip legs run long.
    assert all((s.end - s.start).total_seconds() < 50 * 60 or s.distance > 40 for s in drives)
    charges = [s for s in sessions if s.kind == "charge"]
    assert all(s.end_battery is None or s.end_battery >= 69 for s in charges)
