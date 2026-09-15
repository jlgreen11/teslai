"""Owner-facing HTTP API and day view.

Every route except /healthz, /login and the login API requires the owner's
session cookie (teslai.owner_auth). The API still serves no location data.
"""

from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import Engine, create_engine, text

from teslai import __version__, owner_auth
from teslai.days import day_window, summarize_day
from teslai.db import repo
from teslai.settings import Settings

STATIC = Path(__file__).parent / "static"


PUBLIC_PATHS = {"/healthz", "/login", "/api/v1/login"}


class LoginBody(BaseModel):
    email: str
    password: str
    code: str


def create_app(engine: Engine | None = None, account_id: int | None = None,
               require_login: bool = True, session_secret: str | None = None,
               cipher=None, secure_cookies: bool = True) -> FastAPI:
    app = FastAPI(title="teslai", version=__version__)
    state: dict = {"engine": engine, "account_id": account_id, "cipher": cipher}

    def secret() -> str:
        return session_secret or Settings().teslai_session_secret

    def get_cipher():
        if state["cipher"] is None:
            from teslai.secrets import SecretPaths
            from teslai.tesla.tokens import load_or_create_cipher

            state["cipher"] = load_or_create_cipher(
                SecretPaths(Settings().teslai_secrets_dir).root / "token.key")
        return state["cipher"]

    @app.middleware("http")
    async def require_owner(request: Request, call_next):
        if not require_login or request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        if owner_auth.read_session(request.cookies.get(owner_auth.SESSION_COOKIE), secret()) is None:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Login required."}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)

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
        from teslai.costs import load_tariffs

        return asdict(summarize_day(day, tz, rows, tariffs=load_tariffs()))

    @app.get("/api/v1/vehicles/{vehicle_id}/battery")
    def battery(vehicle_id: int, min_level: float = 50.0):
        from teslai.battery import build_report

        with eng().connect() as conn:
            a = account(conn)
            vid, tz = vehicle(conn, a, vehicle_id)
            rows = repo.charge_range_points(conn, a, vid)
        return asdict(build_report(rows, tz, min_level=min_level))

    def _local_range(conn, vehicle_id: int, start: date, end: date):
        if end < start:
            raise HTTPException(422, "end must not be before start")
        if (end - start).days > 3660:
            raise HTTPException(422, "range is limited to 10 years")
        a = account(conn)
        vid, tz = vehicle(conn, a, vehicle_id)
        range_start, _ = day_window(start, tz)
        _, range_end = day_window(end, tz)
        return a, vid, tz, range_start, range_end

    @app.get("/api/v1/vehicles/{vehicle_id}/totals")
    def period_totals(vehicle_id: int, start: date = Query(...), end: date = Query(...),
                      group: str = "month"):
        from teslai.costs import load_tariffs
        from teslai.totals import FORMATS, totals

        if group not in FORMATS:
            raise HTTPException(422, f"group must be one of {sorted(FORMATS)}")
        with eng().connect() as conn:
            a, vid, tz, rs, re_ = _local_range(conn, vehicle_id, start, end)
            rows = repo.sessions_between(conn, a, vid, rs, re_)
        return totals(rows, tz, group, tariffs=load_tariffs())

    @app.get("/api/v1/vehicles/{vehicle_id}/sessions.csv")
    def sessions_export(vehicle_id: int, start: date = Query(...), end: date = Query(...),
                        kind: str | None = None):
        from teslai.costs import load_tariffs
        from teslai.totals import sessions_csv

        if kind is not None and kind not in {"drive", "charge", "idle", "sleep", "unreachable"}:
            raise HTTPException(422, "unknown kind")
        with eng().connect() as conn:
            a, vid, tz, rs, re_ = _local_range(conn, vehicle_id, start, end)
            rows = repo.sessions_between(conn, a, vid, rs, re_, kind=kind)
        filename = f"teslai-{kind or 'sessions'}-{start}-{end}.csv"
        return PlainTextResponse(sessions_csv(rows, tz, tariffs=load_tariffs()), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}"'})

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

    @app.post("/api/v1/login")
    def login(body: LoginBody, response: Response):
        from datetime import UTC
        from datetime import datetime as dt

        now = dt.now(UTC)
        outcome = "invalid"
        user_id = None
        # Decide and record the outcome inside the transaction, then raise after it
        # commits, so failed-attempt counters are never rolled back.
        with eng().begin() as conn:
            user = conn.execute(text(
                "SELECT id, password_hash, totp_secret_enc, failed_logins, locked_until "
                "FROM users WHERE lower(email) = lower(:e) FOR UPDATE"), {"e": body.email}).first()
            if user is not None and user.locked_until and user.locked_until > now:
                outcome = "locked"
            elif (user is not None and user.password_hash and user.totp_secret_enc
                  and owner_auth.verify_password(body.password, user.password_hash)
                  and owner_auth.verify_totp(
                      get_cipher().decrypt(bytes(user.totp_secret_enc)).decode(), body.code)):
                outcome = "ok"
                user_id = user.id
                conn.execute(text("UPDATE users SET failed_logins = 0, locked_until = NULL "
                                  "WHERE id = :i"), {"i": user.id})
            elif user is not None:
                failures = user.failed_logins + 1
                locked = now + owner_auth.LOCKOUT if failures >= owner_auth.MAX_FAILURES else None
                conn.execute(text("UPDATE users SET failed_logins = :f, locked_until = :l "
                                  "WHERE id = :i"),
                             {"f": 0 if locked else failures, "l": locked, "i": user.id})
        if outcome == "locked":
            raise HTTPException(429, "Too many attempts. Try again later.")
        if outcome != "ok":
            raise HTTPException(401, "Email, password or code is incorrect.")
        response.set_cookie(owner_auth.SESSION_COOKIE, owner_auth.sign_session(user_id, secret()),
                            max_age=int(owner_auth.SESSION_TTL.total_seconds()), httponly=True,
                            secure=secure_cookies, samesite="strict")
        return {"ok": True}

    @app.post("/api/v1/logout")
    def logout(response: Response):
        response.delete_cookie(owner_auth.SESSION_COOKIE)
        return {"ok": True}

    @app.get("/login")
    def login_page():
        return FileResponse(STATIC / "login.html")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app


app = create_app()
