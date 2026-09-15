"""Live session building from stored telemetry.

The worker only stores events. This job turns them into sessions on a rolling
window, so drives and charges from the car appear shortly after they happen:

    anchor = end of the newest session that finished before (now − window),
             or now − window if there is none
    events and connectivity from (anchor − warmup) to now
        │  SessionBuilder (reducer warms up on the extra hour of history)
        ▼
    replace sessions starting at or after anchor, tagged with places

Sessions before the anchor are never touched, so imported TeslaFi history is safe.
Re-running with the same data gives the same sessions; late events inside the
window are picked up on the next run.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text

from teslai.builder import BuilderParams, Connectivity, SessionBuilder
from teslai.db import repo
from teslai.samples import enrich_sessions, samples_from_events, upsert_samples

WINDOW = timedelta(hours=48)
WARMUP = timedelta(hours=1)


def _anchor(conn, account_id: int, vehicle_id: int, now: datetime, window: timedelta) -> datetime:
    cutoff = now - window
    last_closed = conn.execute(text(
        "SELECT max(end_ts) FROM sessions WHERE account_id = :a AND vehicle_id = :v "
        "AND end_ts IS NOT NULL AND end_ts <= :c"), {"a": account_id, "v": vehicle_id, "c": cutoff}).scalar()
    return last_closed or cutoff


def rebuild_recent(engine: Engine, account_id: int, vehicle_id: int, now: datetime | None = None,
                   window: timedelta = WINDOW, params: BuilderParams | None = None,
                   pack_kwh: float = 75.0) -> int:
    """Rebuild a vehicle's recent sessions from telemetry. Returns sessions written."""
    now = now or datetime.now(UTC)
    params = params or BuilderParams()
    with engine.begin() as conn:
        anchor = _anchor(conn, account_id, vehicle_id, now, window)
        start = anchor - WARMUP
        events = repo.events_for_vehicle(conn, account_id, vehicle_id, start, now + timedelta(seconds=1))
        conn_rows = conn.execute(text(
            "SELECT ts, connected FROM connectivity_events WHERE account_id = :a AND vehicle_id = :v "
            "AND ts >= :s AND ts <= :n ORDER BY ts"),
            {"a": account_id, "v": vehicle_id, "s": start, "n": now}).all()
        if not events and not conn_rows:
            return 0
        builder = SessionBuilder(params=params)
        builder.feed(events, [Connectivity(r.ts, r.connected) for r in conn_rows])
        sessions = builder.finalize(now)
        upsert_samples(conn, account_id, vehicle_id,
                       (x for x in samples_from_events(events) if x["ts"] >= anchor), "telemetry")
        written = repo.replace_sessions(conn, account_id, vehicle_id, anchor, now + timedelta(seconds=1),
                                        sessions, "telemetry", params.version,
                                        places=repo.list_places(conn, account_id))
        enrich_sessions(conn, account_id, vehicle_id, anchor, now + timedelta(seconds=1), pack_kwh)
        return written


def rebuild_all(engine: Engine, account_id: int, now: datetime | None = None) -> dict[int, int]:
    with engine.connect() as conn:
        vehicle_ids = conn.execute(text("SELECT id FROM vehicles WHERE account_id = :a"),
                                   {"a": account_id}).scalars().all()
    return {vid: rebuild_recent(engine, account_id, vid, now) for vid in vehicle_ids}
