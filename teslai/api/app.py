"""Owner-facing HTTP API and day view.

Phase 1 binds to localhost only and serves no location data. Owner login ships in
phase 2, before this API is reachable from outside the machine or returns
locations (docs/ARCHITECTURE.md, section 10).
"""

from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import Engine, create_engine, text

from teslai import __version__
from teslai.days import day_window, summarize_day
from teslai.db import repo
from teslai.settings import Settings

STATIC = Path(__file__).parent / "static"


def create_app(engine: Engine | None = None, account_id: int | None = None) -> FastAPI:
    app = FastAPI(title="teslai", version=__version__)
    state: dict = {"engine": engine, "account_id": account_id}

    def eng() -> Engine:
        if state["engine"] is None:
            state["engine"] = create_engine(Settings().database_url)
        return state["engine"]

    def account(conn) -> int:
        if state["account_id"] is not None:
            return state["account_id"]
        ids = conn.execute(text("SELECT id FROM accounts ORDER BY id LIMIT 2")).scalars().all()
        if len(ids) != 1:
            raise HTTPException(503, "Expected exactly one account in personal mode.")
        return ids[0]

    def vehicle(conn, account_id: int, vehicle_id: int) -> tuple[int, ZoneInfo]:
        row = conn.execute(
            text("SELECT id, timezone FROM vehicles WHERE id = :v AND account_id = :a"),
            {"v": vehicle_id, "a": account_id}).first()
        if row is None:
            raise HTTPException(404, f"Vehicle {vehicle_id} not found.")
        return row.id, ZoneInfo(row.timezone)

    @app.get("/healthz")
    def healthz():
        with eng().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "version": __version__}

    @app.get("/api/v1/vehicles")
    def vehicles():
        with eng().connect() as conn:
            a = account(conn)
            rows = conn.execute(
                text("SELECT id, display_name, timezone, right(vin, 4) AS vin_last4 "
                     "FROM vehicles WHERE account_id = :a ORDER BY id"), {"a": a}).all()
        return [dict(r._mapping) for r in rows]

    @app.get("/api/v1/vehicles/{vehicle_id}/days/{day}")
    def day_view(vehicle_id: int, day: date):
        with eng().connect() as conn:
            a = account(conn)
            vid, tz = vehicle(conn, a, vehicle_id)
            start, end = day_window(day, tz)
            rows = repo.sessions_overlapping(conn, a, vid, start, end)
        return asdict(summarize_day(day, tz, rows))

    @app.get("/api/v1/vehicles/{vehicle_id}/sessions")
    def sessions(vehicle_id: int, start: datetime = Query(...), end: datetime = Query(...),
                 kind: str | None = None):
        if end <= start:
            raise HTTPException(422, "end must be after start")
        if start.tzinfo is None or end.tzinfo is None:
            raise HTTPException(422, "start and end must include a UTC offset")
        with eng().connect() as conn:
            a = account(conn)
            vid, tz = vehicle(conn, a, vehicle_id)
            rows = repo.sessions_between(conn, a, vid, start, end, kind=kind)
        return summarize_day(start.date(), tz, rows).sessions

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app


app = create_app()
