"""teslai operator CLI."""

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
    }
    body = _render_env(template, values)
    if "POSTGRES_PASSWORD=" not in body:
        body += f"POSTGRES_PASSWORD={db_password}\n"
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


if __name__ == "__main__":
    app()
