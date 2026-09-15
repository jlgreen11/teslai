"""teslai operator CLI."""

import os
import secrets as pysecrets
from pathlib import Path

import typer

from teslai.doctor import run_checks
from teslai.errors import CATALOG
from teslai.secrets import (
    SecretPaths,
    generate_app_keys,
    generate_ca,
    generate_server_cert,
)

app = typer.Typer(help="teslai: personal Tesla data logger.", no_args_is_help=True)
errors_app = typer.Typer(help="Error catalog.")
app.add_typer(errors_app, name="errors")
import_app = typer.Typer(help="Import history from other loggers.")
app.add_typer(import_app, name="import")
gate_app = typer.Typer(help="Validation gates for migration and cutover.")
app.add_typer(gate_app, name="gate")
tesla_app = typer.Typer(help="Tesla developer app, login and pairing.")
app.add_typer(tesla_app, name="tesla")
telemetry_app = typer.Typer(help="The car's Fleet Telemetry config.")
app.add_typer(telemetry_app, name="telemetry")
db_app = typer.Typer(help="Database migrations.")
app.add_typer(db_app, name="db")
owner_app = typer.Typer(help="Owner login for the web app.")
app.add_typer(owner_app, name="owner")


@owner_app.command("create")
def owner_create(email: str = typer.Option(..., help="Login email.")) -> None:
    """Create or reset the owner's password and authenticator code."""
    from sqlalchemy import create_engine, text

    from teslai import owner_auth
    from teslai.db import repo
    from teslai.settings import Settings
    from teslai.tesla.tokens import load_or_create_cipher

    s = Settings()
    password = typer.prompt("Password (12+ characters)", hide_input=True,
                            confirmation_prompt=True)
    try:
        pw_hash = owner_auth.hash_password(password)
    except ValueError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(2) from None
    secret = owner_auth.new_totp_secret()
    typer.echo("\nAdd this to your authenticator app:")
    typer.echo(f"  {owner_auth.provisioning_uri(secret, email)}")
    typer.echo(f"  (or enter the key manually: {secret})\n")
    code = typer.prompt("Enter the 6-digit code it shows")
    if not owner_auth.verify_totp(secret, code):
        typer.echo("That code does not match; nothing was saved. Run the command again.", err=True)
        raise typer.Exit(1)
    cipher = load_or_create_cipher(SecretPaths(s.teslai_secrets_dir).root / "token.key")
    engine = create_engine(s.database_url)
    with engine.begin() as conn:
        ids = conn.execute(text("SELECT id FROM accounts ORDER BY id LIMIT 2")).scalars().all()
        account_id = ids[0] if len(ids) == 1 else repo.create_account(conn, "owner")
        conn.execute(text("""
            INSERT INTO users (account_id, email, password_hash, totp_secret_enc)
            VALUES (:a, :e, :p, :t)
            ON CONFLICT (account_id, email) DO UPDATE SET password_hash = EXCLUDED.password_hash,
                totp_secret_enc = EXCLUDED.totp_secret_enc, failed_logins = 0, locked_until = NULL"""),
            {"a": account_id, "e": email, "p": pw_hash, "t": cipher.encrypt(secret.encode())})
    typer.echo(f"Owner login saved for {email}.")


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply all database migrations."""
    from alembic import command
    from alembic.config import Config

    from teslai.paths import REPO_DIR
    from teslai.settings import Settings

    cfg = Config(str(REPO_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_DIR / "migrations"))
    cfg.attributes["url"] = Settings().database_url
    command.upgrade(cfg, "head")
    typer.echo("Database is at the latest migration.")


def http_client(**kwargs):
    """Factory so tests can swap in a mock transport."""
    import httpx

    return httpx.Client(timeout=30, **kwargs)


def _fail(err) -> None:
    typer.echo(str(err), err=True)
    raise typer.Exit(1) from None

ENV_EXAMPLE = Path(".env.example")


def _render_env(template: str, values: dict[str, str]) -> str:
    out = []
    for line in template.splitlines():
        key = line.split("=", 1)[0] if "=" in line and not line.startswith("#") else None
        if key in values:
            out.append(f"{key}={values[key]}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


@app.command()
def init(
    domain: str = typer.Option(..., help="Domain that will host the Tesla public key."),
    telemetry_host: str = typer.Option("", help="Hostname the car streams to. "
                                       "Defaults to telemetry.<domain>."),
    timezone: str = typer.Option("UTC", help="Home IANA timezone, e.g. America/Chicago."),
    env_file: Path = typer.Option(Path(".env")),
    secrets_dir: Path = typer.Option(Path("./secrets")),
    force: bool = typer.Option(False, help="Overwrite existing .env and secrets."),
    rotate_server_cert: bool = typer.Option(False, help="Reissue only the telemetry server "
                                            "certificate from the existing private CA."),
) -> None:
    """Generate .env, the private telemetry CA, the server certificate and app keys."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        typer.echo(CATALOG["TSL-IMPORT-TZ"].fix, err=True)
        raise typer.Exit(2) from None

    host = telemetry_host or f"telemetry.{domain}"
    paths = SecretPaths(secrets_dir)

    if rotate_server_cert:
        if not paths.ca_key.exists():
            typer.echo("No private CA found; run `teslai init` without --rotate-server-cert.",
                       err=True)
            raise typer.Exit(1)
        generate_server_cert(paths, host)
        typer.echo(f"Reissued {paths.server_cert}. Next: teslai telemetry push "
                   "--reason cert-rotate")
        return

    existing = [p for p in [env_file, *paths.all()] if p.exists()]
    if existing and not force:
        typer.echo("Refusing to overwrite: " + ", ".join(str(p) for p in existing)
                   + ". Pass --force to regenerate.", err=True)
        raise typer.Exit(1)

    secrets_dir.mkdir(parents=True, exist_ok=True)
    secrets_dir.chmod(0o700)
    generate_ca(paths)
    generate_server_cert(paths, host)
    generate_app_keys(paths)
    from teslai.tesla.tokens import load_or_create_cipher

    load_or_create_cipher(secrets_dir / "token.key")

    template = ENV_EXAMPLE.read_text() if ENV_EXAMPLE.exists() else ""
    db_password = pysecrets.token_urlsafe(24)
    values = {
        "TESLAI_DOMAIN": domain,
        "TESLAI_TELEMETRY_HOST": host,
        "TESLAI_SECRETS_DIR": str(secrets_dir),
        "TESLAI_TIMEZONE": timezone,
        "DATABASE_URL": f"postgresql+psycopg://teslai:{db_password}@localhost:5432/teslai",
        "POSTGRES_PASSWORD": db_password,
        "TESLAI_SESSION_SECRET": pysecrets.token_urlsafe(32),
        "TESLAI_UID": str(os.getuid()),
        "TESLAI_GID": str(os.getgid()),
    }
    body = _render_env(template, values)
    for key in ("POSTGRES_PASSWORD", "TESLAI_UID", "TESLAI_GID"):
        if f"{key}=" not in body:
            body += f"{key}={values.get(key, db_password)}\n"
    env_file.write_text(body)
    env_file.chmod(0o600)
    typer.echo(f"Wrote {env_file} and secrets in {secrets_dir}.")
    typer.echo(f"Public key to host: https://{domain}/.well-known/appspecific/"
               "com.tesla.3p.public-key.pem")
    typer.echo("Next: docker compose up -d, then teslai doctor")


@app.command()
def doctor(
    env_file: Path = typer.Option(Path(".env")),
    offline: bool = typer.Option(False, help="Skip network checks."),
) -> None:
    """Run health checks in order and explain the first failure."""
    results = run_checks(env_file, network=not offline)
    failed = None
    for r in results:
        mark = "skip" if r.skipped else ("ok  " if r.ok else "FAIL")
        typer.echo(f"[{mark}] {r.name}{' — ' + r.detail if r.detail else ''}")
        if r.skipped and r.info:
            typer.echo(f"       {r.info.code}: {r.info.fix}")
        if not r.ok and not r.skipped and failed is None:
            failed = r
    if failed and failed.info:
        i = failed.info
        typer.echo(f"\n{i.code}: {i.problem}\n  Likely cause: {i.cause}\n  Fix: {i.fix}\n"
                   f"  Docs: {i.anchor}")
        raise typer.Exit(1)


@errors_app.command("list")
def errors_list() -> None:
    """Print every error code."""
    for code, info in CATALOG.items():
        typer.echo(f"{code}: {info.problem}")


@errors_app.command("docs")
def errors_docs(out: Path = typer.Option(Path("docs/errors.md"))) -> None:
    """Regenerate docs/errors.md from the catalog."""
    lines = ["# Error catalog", "", "Generated by `teslai errors docs`. Do not edit by hand.", ""]
    for code, i in CATALOG.items():
        lines += [f"## {code.lower()}", "", f"**{code}**: {i.problem}", "",
                  f"- **Likely cause:** {i.cause}", f"- **Fix:** {i.fix}", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    typer.echo(f"Wrote {out}")


def _require_tz(tz: str | None):
    from teslai.errors import TeslaiError
    from teslai.importer.teslafi import resolve_timezone

    try:
        return resolve_timezone(tz)
    except TeslaiError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(2) from None


def _print_import(result, zone) -> None:
    from teslai.gate import totals_from_sessions

    for r in result.reports:
        typer.echo(f"{r.path.name}: read {r.rows_read}, imported {r.rows_imported}, "
                   f"skipped {len(r.skipped)}, DST ambiguous {r.ambiguous_resolved}, "
                   f"DST gap {r.nonexistent_shifted}, out of order {r.out_of_order}")
        for line, why in r.skipped[:5]:
            typer.echo(f"    line {line}: {why}")
    totals = totals_from_sessions(result.sessions, zone)
    typer.echo("\nmonth     drives    miles  charges  kWh added")
    for month, t in sorted(totals.items()):
        typer.echo(f"{month}  {t.drive_count:>6}  {t.miles:>7.1f}  {t.charge_count:>7}  "
                   f"{t.kwh_added:>9.1f}")


@import_app.command("teslafi")
def import_teslafi_cmd(
    paths: list[Path] = typer.Argument(..., help="TeslaFi CSV files or directories."),
    tz: str = typer.Option(None, "--tz", help="TeslaFi home timezone (IANA), required."),
    vin: str = typer.Option("", help="VIN to store sessions under (with --write)."),
    write: bool = typer.Option(False, help="Store sessions in the database. Default is a dry run."),
) -> None:
    """Import TeslaFi history through the session builder."""
    from teslai.builder import BuilderParams
    from teslai.importer.run import import_teslafi

    zone = _require_tz(tz)
    params = BuilderParams()
    result = import_teslafi(paths, tz, params=params)
    _print_import(result, zone)
    if not write:
        typer.echo("\nDry run: nothing stored. Re-run with --write --vin <VIN> to store.")
        return
    if not vin or result.first_ts is None:
        typer.echo("--write needs --vin and at least one imported row.", err=True)
        raise typer.Exit(2)
    from datetime import timedelta

    from sqlalchemy import create_engine, text

    from teslai.db import repo
    from teslai.settings import Settings

    engine = create_engine(Settings().database_url)
    with engine.begin() as conn:
        found = conn.execute(text("SELECT id, account_id FROM vehicles WHERE vin = :v"),
                             {"v": vin}).first()
        if found is None:
            account_id = repo.create_account(conn, "owner")
            vehicle_id = repo.create_vehicle(conn, account_id, vin, timezone=tz)
        else:
            vehicle_id, account_id = found
        n = repo.replace_sessions(conn, account_id, vehicle_id, result.first_ts,
                                  result.last_ts + timedelta(seconds=1), result.sessions,
                                  "teslafi_import", params.version)
    typer.echo(f"\nStored {n} sessions for VIN ending {vin[-4:]}.")


@gate_app.command("history")
def gate_history_cmd(
    paths: list[Path] = typer.Argument(..., help="TeslaFi CSV files or directories."),
    answer_key: list[Path] = typer.Option(..., "--answer-key",
                                          help="TeslaFi drives/charges JSON, or monthly totals."),
    tz: str = typer.Option(None, "--tz", help="TeslaFi home timezone (IANA), required."),
    switch_date: str = typer.Option("", help="Date TeslaFi switched to streaming, YYYY-MM-DD."),
    report: Path = typer.Option(None, help="Write the full result as JSON."),
) -> None:
    """Compare derived sessions with TeslaFi's own history, month by month."""
    import json as _json
    from datetime import date

    from teslai.errors import TeslaiError
    from teslai.gate import compare, render_table, summarize, totals_from_sessions
    from teslai.importer.answer_key import load_answer_key
    from teslai.importer.run import import_teslafi

    zone = _require_tz(tz)
    try:
        theirs = load_answer_key(answer_key, zone)
    except TeslaiError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(2) from None
    result = import_teslafi(paths, tz)
    ours = totals_from_sessions(result.sessions, zone)
    switch = date.fromisoformat(switch_date) if switch_date else None
    results = compare(ours, theirs, switch_date=switch)
    typer.echo(render_table(results))
    summary = summarize(results)
    for era, s in summary.items():
        typer.echo(f"{era}: {s['passed']}/{s['months']} months pass")
    if report:
        report.write_text(_json.dumps([
            {"month": r.month, "era": r.era, "ok": r.ok, "odometer_ok": r.odometer_ok,
             "notes": r.notes,
             "metrics": [{"metric": m.metric, "ours": m.ours, "theirs": m.theirs, "ok": m.ok}
                         for m in r.metrics]} for r in results], indent=2))
    if not all(r.ok for r in results):
        raise typer.Exit(1)


@app.command()
def worker(
    client_id: str = typer.Option("teslai-worker", help="Fixed MQTT client id for durable sessions."),
) -> None:
    """Consume fleet-telemetry messages from MQTT into the database."""
    import logging
    import time

    from sqlalchemy import create_engine

    from teslai import worker as worker_mod
    from teslai.settings import Settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = Settings()
    engine = create_engine(s.database_url)
    while True:
        try:
            account_id = worker_mod.single_account_id(engine)
            break
        except Exception as err:  # noqa: BLE001 - keep waiting for first import or login
            reason = str(err).splitlines()[0][:160]
            logging.getLogger("teslai.worker").warning(
                "waiting for an account (run an import or teslai tesla login): %s", reason)
            time.sleep(60)
    worker_mod.run(engine, s.mqtt_host, s.mqtt_port, s.mqtt_topic_base, client_id=client_id,
                   account_id=account_id,
                   recordings_dir=str(s.teslai_recordings_dir) if s.teslai_recordings_dir else None)


@app.command()
def replay(
    paths: list[Path] = typer.Argument(..., help="Recording files or directories."),
    dry_run: bool = typer.Option(False, help="Count records without writing."),
) -> None:
    """Replay recorded MQTT payloads through the ingest path."""
    from sqlalchemy import create_engine

    from teslai import worker as worker_mod
    from teslai.recorder import read_records
    from teslai.settings import Settings

    records = list(read_records(paths))
    typer.echo(f"{len(records)} records"
               + (f" from {records[0].received_at:%Y-%m-%d %H:%M} to "
                  f"{records[-1].received_at:%Y-%m-%d %H:%M} UTC" if records else ""))
    if dry_run or not records:
        return
    engine = create_engine(Settings().database_url)
    ingestor = worker_mod.Ingestor(engine, worker_mod.single_account_id(engine))
    for r in records:
        ingestor.handle(r.topic, r.payload, r.received_at)
    typer.echo("Replay complete.")


@tesla_app.command("register")
def tesla_register() -> None:
    """Register the developer app for TESLA_REGION and verify the hosted public key."""
    from teslai.errors import TeslaiError
    from teslai.settings import Settings
    from teslai.tesla import auth
    from teslai.tesla.regions import base_url

    s = Settings()
    if not s.tesla_client_id or not s.tesla_client_secret:
        _fail(TeslaiError("TSL-TESLA-UNCONFIGURED"))
    try:
        base = base_url(s.tesla_region)
        with http_client() as http:
            token = auth.partner_token(http, s.tesla_client_id, s.tesla_client_secret, base)
            auth.register_partner(http, base, token, s.teslai_domain)
            remote = auth.registered_public_key(http, base, token, s.teslai_domain)
    except TeslaiError as err:
        _fail(err)
    local = SecretPaths(s.teslai_secrets_dir).app_public_key.read_bytes()
    if not auth.public_key_matches(remote, local):
        typer.echo("Registered, but Tesla's stored key does not match secrets/"
                   "com.tesla.3p.public-key.pem. Check the file served at https://"
                   f"{s.teslai_domain}/.well-known/appspecific/com.tesla.3p.public-key.pem",
                   err=True)
        raise typer.Exit(1)
    typer.echo(f"Registered {s.teslai_domain} in region {s.tesla_region}; public key verified.")
    typer.echo("Next: teslai tesla login")


@tesla_app.command("login")
def tesla_login() -> None:
    """Authorize teslai for the owner's Tesla account and store encrypted tokens."""
    import secrets as _secrets
    from urllib.parse import parse_qs, urlparse

    from sqlalchemy import create_engine, text

    from teslai.db import repo
    from teslai.errors import TeslaiError
    from teslai.settings import Settings
    from teslai.tesla import auth
    from teslai.tesla.regions import base_url
    from teslai.tesla.tokens import load_or_create_cipher, save_tokens

    s = Settings()
    if not (s.tesla_client_id and s.tesla_client_secret and s.tesla_redirect_uri):
        _fail(TeslaiError("TSL-ENV-INCOMPLETE",
                          "TESLA_CLIENT_ID, TESLA_CLIENT_SECRET and TESLA_REDIRECT_URI are required"))
    state = _secrets.token_urlsafe(16)
    typer.echo("Open this link, approve access, then paste the full URL you were redirected to:\n")
    typer.echo(auth.authorize_url(s.tesla_client_id, s.tesla_redirect_uri, state))
    pasted = typer.prompt("\nRedirected URL")
    q = parse_qs(urlparse(pasted.strip()).query)
    if q.get("state", [""])[0] != state or "code" not in q:
        typer.echo("The URL has no code or the state does not match; start again.", err=True)
        raise typer.Exit(1)
    try:
        with http_client() as http:
            tokens = auth.exchange_code(http, s.tesla_client_id, s.tesla_client_secret,
                                        q["code"][0], s.tesla_redirect_uri, base_url(s.tesla_region))
    except TeslaiError as err:
        _fail(err)
    engine = create_engine(s.database_url)
    with engine.begin() as conn:
        ids = conn.execute(text("SELECT id FROM accounts ORDER BY id LIMIT 2")).scalars().all()
        account_id = ids[0] if len(ids) == 1 else repo.create_account(conn, "owner")
    cipher = load_or_create_cipher(SecretPaths(s.teslai_secrets_dir).root / "token.key")
    save_tokens(engine, cipher, account_id, s.tesla_client_id, s.tesla_region,
                auth.LOGGING_SCOPES, tokens)
    typer.echo("Tesla login stored. Next: teslai pair")


@app.command()
def pair() -> None:
    """Show the link that installs teslai's virtual key on the car."""
    from teslai.settings import Settings

    s = Settings()
    link = f"https://tesla.com/_ak/{s.teslai_domain}"
    typer.echo("On the phone that has the Tesla app, near the car, open:\n")
    typer.echo(f"  {link}\n")
    typer.echo("Approve the key in the Tesla app, then run: teslai telemetry push --yes")


def _desired_body():
    from datetime import UTC, datetime, timedelta

    from teslai.config import default_field_specs
    from teslai.settings import Settings
    from teslai.tesla.telemetry_config import desired_config, request_body

    s = Settings()
    ca = SecretPaths(s.teslai_secrets_dir).ca_cert.read_text()
    exp = datetime.now(UTC) + timedelta(days=s.tesla_telemetry_exp_days)
    config = desired_config(default_field_specs(), s.teslai_telemetry_host,
                            s.teslai_telemetry_port, ca, exp)
    return s, request_body([s.tesla_vin] if s.tesla_vin else [], config)


def _access_token(s) -> str:
    from sqlalchemy import create_engine

    from teslai.tesla import auth
    from teslai.tesla.tokens import get_access_token, load_or_create_cipher
    from teslai.worker import single_account_id

    engine = create_engine(s.database_url)
    cipher = load_or_create_cipher(SecretPaths(s.teslai_secrets_dir).root / "token.key")
    with http_client() as http:
        return get_access_token(engine, cipher, single_account_id(engine),
                                lambda rt: auth.refresh(http, s.tesla_client_id, rt))


@telemetry_app.command("server-config")
def telemetry_server_config(
    out: Path = typer.Option(Path("secrets/fleet-telemetry.json"),
                             help="Where to write fleet-telemetry's config."),
) -> None:
    """Write fleet-telemetry's server config and create the signing proxy's certificate."""
    from teslai.server_config import ensure_proxy_cert, write_fleet_telemetry_config
    from teslai.settings import Settings

    s = Settings()
    paths = SecretPaths(s.teslai_secrets_dir)
    write_fleet_telemetry_config(out, port=s.teslai_telemetry_port, topic_base=s.mqtt_topic_base)
    cert, _ = ensure_proxy_cert(paths)
    typer.echo(f"Wrote {out} and {cert}.")
    typer.echo("Start the edge services: docker compose --profile edge up -d")


@telemetry_app.command("push")
def telemetry_push(
    yes: bool = typer.Option(False, "--yes", help="Send the config. Without it, only show it."),
    awake_hours: float = typer.Option(3.0, help="Awake hours per day for the cost upper bound."),
    reason: str = typer.Option("", help="Why this push happens, recorded in the output."),
) -> None:
    """Push telemetry.yaml to the car through the signing proxy."""
    from teslai.config import default_field_specs
    from teslai.errors import CATALOG, TeslaiError
    from teslai.tesla.telemetry_config import monthly_signal_upper_bound, push

    try:
        s, body = _desired_body()
    except TeslaiError as err:
        _fail(err)
    signals, usd = monthly_signal_upper_bound(default_field_specs(), awake_hours)
    typer.echo(f"{len(body['config']['fields'])} fields to {body['config']['hostname']}:"
               f"{body['config']['port']}, CA from the private telemetry CA.")
    typer.echo(f"Cost upper bound: {signals:,} signals ≈ ${usd:.2f}/month at {awake_hours} awake "
               "hours/day. Actual cost is lower; fields send only on change.")
    if reason:
        typer.echo(f"Reason: {reason}")
    if not yes:
        typer.echo("Dry run. Re-run with --yes to push.")
        return
    try:
        token = _access_token(s)
        verify = str(s.tesla_proxy_ca) if s.tesla_proxy_ca else True
        with http_client(verify=verify) as http:
            result = push(http, s.tesla_proxy_url, token, body)
    except TeslaiError as err:
        _fail(err)
    typer.echo(f"Updated {result.updated_vehicles} vehicle(s).")
    for vin, code in result.problems:
        i = CATALOG[code]
        typer.echo(f"VIN ending {vin[-4:]}: {code}: {i.problem}\n  Fix: {i.fix}", err=True)
    if result.problems:
        raise typer.Exit(1)
    typer.echo("Next: teslai telemetry status")


@telemetry_app.command("status")
def telemetry_status() -> None:
    """Show whether the car has synced the desired config, and what is wrong if not."""
    from teslai.errors import CATALOG, TeslaiError
    from teslai.tesla.regions import base_url
    from teslai.tesla.telemetry_config import check_status, diff, fetch

    try:
        s, body = _desired_body()
        token = _access_token(s)
        with http_client() as http:
            status = fetch(http, base_url(s.tesla_region), token, s.tesla_vin)
    except TeslaiError as err:
        _fail(err)
    typer.echo(f"synced: {status.synced}   limit_reached: {status.limit_reached}")
    for change in diff(body["config"], status.config):
        typer.echo(f"  diff: {change}")
    codes = check_status(status, body["config"])
    for code in codes:
        i = CATALOG[code]
        typer.echo(f"{code}: {i.problem}\n  Fix: {i.fix}")
    if codes:
        raise typer.Exit(1)
    typer.echo("Telemetry config is synced and current.")


@app.command()
def monitor(
    once: bool = typer.Option(False, help="Run the checks once and exit."),
    interval: int = typer.Option(60, help="Seconds between checks."),
) -> None:
    """Evaluate health rules, notify on new and resolved alerts, keep the Tesla login fresh."""
    import logging
    import time
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine

    from teslai import alerts
    from teslai.settings import Settings
    from teslai.worker import single_account_id

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("teslai.monitor")
    s = Settings()
    urls = [u.strip() for u in s.teslai_notify_urls.split(",") if u.strip()]

    def notify(title: str, body: str) -> None:
        log.warning("%s | %s", title, body.replace("\n", " | "))
        if urls:
            alerts.apprise_notifier(urls)(title, body)

    engine = create_engine(s.database_url)
    cert = SecretPaths(s.teslai_secrets_dir).server_cert
    last_refresh_attempt = datetime.min.replace(tzinfo=UTC)
    while True:
        try:
            account_id = single_account_id(engine)
            result = alerts.run_once(engine, account_id, notify, server_cert=cert,
                                     backup_dir=s.teslai_backup_dir)
            log.info("checks done: %d fired, %d resolved", len(result["fired"]), len(result["resolved"]))
            now = datetime.now(UTC)
            if s.tesla_client_id and now - last_refresh_attempt > timedelta(days=7):
                last_refresh_attempt = now
                try:
                    _access_token(s)
                except Exception as err:  # noqa: BLE001 - reported, retried next week
                    log.warning("Tesla token refresh failed: %s", str(err).splitlines()[0])
        except Exception as err:  # noqa: BLE001 - monitor must keep running
            log.warning("monitor cycle failed: %s", str(err).splitlines()[0][:200])
        if once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    app()
