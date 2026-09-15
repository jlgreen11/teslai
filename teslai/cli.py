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


if __name__ == "__main__":
    app()
