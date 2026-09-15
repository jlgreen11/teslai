"""Health rules and notifications.

Each check returns the conditions that are currently true. run_once() compares
them with open firings:

    condition true,  no open firing    -> insert firing, notify "alert"
    condition true,  open firing       -> nothing (no repeat notifications)
    condition false, open firing       -> resolve firing, notify "resolved"

A partial unique index on open firings makes a concurrent duplicate insert fail
instead of double-notifying.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, text

from teslai.errors import CATALOG

INFORMATIONAL_CODES = {"TSL-NEW-SOFTWARE"}
PRICES = {"signal": 0.0001, "command": 0.001, "data": 0.002, "wake": 0.02}
MONTHLY_CREDIT = 10.0


@dataclass(frozen=True)
class Condition:
    rule: str
    key: str
    code: str
    detail: str
    informational: bool = False


Notifier = Callable[[str, str], None]  # (title, body)


def month_cost(counts: dict[str, int]) -> float:
    return round(sum(PRICES.get(cat, 0.0) * n for cat, n in counts.items()), 4)


def check_billing(conn, account_id: int, now: datetime,
                  thresholds: tuple[int, ...] = (50, 80)) -> list[Condition]:
    start = now.date().replace(day=1)
    rows = conn.execute(text("SELECT category, sum(count) AS n FROM api_usage "
                             "WHERE account_id = :a AND day >= :s GROUP BY category"),
                        {"a": account_id, "s": start}).all()
    cost = month_cost({r.category: int(r.n) for r in rows})
    used = cost / MONTHLY_CREDIT * 100
    return [Condition("billing", str(t), "TSL-BILLING-THRESHOLD",
                      f"${cost:.2f} of the ${MONTHLY_CREDIT:.0f} credit used this month ({used:.0f}%)")
            for t in thresholds if used >= t]


def check_ingest_silence(conn, account_id: int, now: datetime,
                         silent_after: timedelta = timedelta(minutes=15)) -> list[Condition]:
    rows = conn.execute(text("""
        SELECT v.id, right(v.vin, 4) AS last4,
               (SELECT connected FROM connectivity_events c WHERE c.vehicle_id = v.id
                  ORDER BY ts DESC LIMIT 1) AS connected,
               (SELECT ts FROM connectivity_events c WHERE c.vehicle_id = v.id
                  ORDER BY ts DESC LIMIT 1) AS connected_since,
               (SELECT max(received_at) FROM telemetry_events e WHERE e.vehicle_id = v.id
                  AND e.received_at > now() - interval '2 days') AS last_event
        FROM vehicles v WHERE v.account_id = :a"""), {"a": account_id}).all()
    out = []
    for r in rows:
        if not r.connected:
            continue
        last = max(x for x in (r.last_event, r.connected_since) if x is not None)
        if now - last > silent_after:
            minutes = int((now - last).total_seconds() // 60)
            out.append(Condition("ingest_silence", str(r.id), "TSL-INGEST-SILENT",
                                 f"car ···{r.last4} connected, no telemetry for {minutes} min"))
    return out


def check_token_age(conn, account_id: int, now: datetime,
                    warn_after: timedelta = timedelta(days=60)) -> list[Condition]:
    updated = conn.execute(text("SELECT updated_at FROM tesla_connections WHERE account_id = :a"),
                           {"a": account_id}).scalar()
    if updated is not None and now - updated > warn_after:
        return [Condition("token_age", "", "TSL-TOKEN-AGING",
                          f"last refreshed {(now - updated).days} days ago")]
    return []


def check_cert(server_cert: Path, now: datetime) -> list[Condition]:
    from teslai.secrets import cert_days_left

    if not server_cert.exists():
        return []
    days = cert_days_left(server_cert, now)
    if days < 14:
        return [Condition("cert_expiry", server_cert.name, "TSL-CERT-EXPIRING",
                          f"{days:.1f} days left")]
    return []


def check_backups(backup_dir: Path, now: datetime, stale_after: timedelta = timedelta(hours=36),
                  verify_stale_after: timedelta = timedelta(days=8)) -> list[Condition]:
    import json

    if not backup_dir.exists():
        return [Condition("backup", "missing", "TSL-BACKUP-STALE", f"{backup_dir} does not exist")]
    dumps = sorted(backup_dir.glob("teslai-*.dump"), key=lambda p: p.stat().st_mtime)
    out = []
    if not dumps:
        out.append(Condition("backup", "dump", "TSL-BACKUP-STALE", "no backups yet"))
    else:
        age = now - datetime.fromtimestamp(dumps[-1].stat().st_mtime, UTC)
        if age > stale_after:
            out.append(Condition("backup", "dump", "TSL-BACKUP-STALE",
                                 f"newest backup is {age.total_seconds() / 3600:.0f} hours old"))
    status_file = backup_dir / "last-verify.json"
    if status_file.exists():
        try:
            status = json.loads(status_file.read_text())
            verified = datetime.fromisoformat(status["verified_at"])
        except (ValueError, KeyError):
            return out + [Condition("backup", "verify", "TSL-BACKUP-STALE", "unreadable restore check")]
        if status.get("status") != "ok":
            out.append(Condition("backup", "verify", "TSL-BACKUP-STALE",
                                 f"restore check failed: {status.get('tables', '')}"))
        elif now - verified > verify_stale_after:
            out.append(Condition("backup", "verify", "TSL-BACKUP-STALE",
                                 f"last restore check {(now - verified).days} days ago"))
    return out


def format_alert(c: Condition, resolved: bool = False) -> tuple[str, str]:
    info = CATALOG[c.code]
    if c.informational or c.code in INFORMATIONAL_CODES:
        return f"teslai: {info.problem}", c.detail
    if resolved:
        return f"Resolved: {info.problem}", f"{c.code} cleared ({c.detail})."
    return (f"teslai: {info.problem}",
            f"{c.code}: {c.detail}\nLikely cause: {info.cause}\nFix: {info.fix}")


def run_once(engine: Engine, account_id: int, notify: Notifier, now: datetime | None = None,
             server_cert: Path | None = None,
             backup_dir: Path | None = None,
             rule_config=None) -> dict[str, list[Condition]]:
    now = now or datetime.now(UTC)
    with engine.connect() as conn:
        current = (check_billing(conn, account_id, now) + check_ingest_silence(conn, account_id, now)
                   + check_token_age(conn, account_id, now))
    if server_cert is not None:
        current += check_cert(server_cert, now)
    if backup_dir is not None:
        current += check_backups(backup_dir, now)
    if rule_config is not None:
        from teslai.db import repo
        from teslai.rules import evaluate, vehicle_states

        with engine.connect() as conn:
            homes = [p for p in repo.list_places(conn, account_id) if p.kind == "home"]
            for vid, last4, state, connected in vehicle_states(conn, account_id, now):
                current += evaluate(vid, last4, state, connected, now, homes, rule_config)
    fired, resolved = [], []
    with engine.begin() as conn:
        open_rows = conn.execute(text("SELECT id, rule, key, code, message FROM rule_firings "
                                      "WHERE account_id = :a AND resolved_at IS NULL FOR UPDATE"),
                                 {"a": account_id}).all()
        open_keys = {(r.rule, r.key): r for r in open_rows}
        current_keys = {(c.rule, c.key) for c in current}
        for c in current:
            if (c.rule, c.key) in open_keys:
                continue
            conn.execute(text("INSERT INTO rule_firings (account_id, rule, key, code, message, fired_at) "
                              "VALUES (:a, :r, :k, :c, :m, :t)"),
                         {"a": account_id, "r": c.rule, "k": c.key, "c": c.code, "m": c.detail, "t": now})
            fired.append(c)
        for (rule, key), row in open_keys.items():
            if (rule, key) not in current_keys:
                conn.execute(text("UPDATE rule_firings SET resolved_at = :t WHERE id = :i"),
                             {"t": now, "i": row.id})
                # Informational rules (such as a new software version) have nothing to resolve.
                if row.code not in INFORMATIONAL_CODES:
                    resolved.append(Condition(rule, key, row.code, row.message))
    for c in fired:
        notify(*format_alert(c))
    for c in resolved:
        notify(*format_alert(c, resolved=True))
    return {"fired": fired, "resolved": resolved}


def apprise_notifier(urls: list[str]) -> Notifier:
    import apprise

    ap = apprise.Apprise()
    for url in urls:
        ap.add(url)

    def notify(title: str, body: str) -> None:
        if not ap.notify(title=title, body=body):
            raise RuntimeError("no notification channel accepted the message")

    return notify
