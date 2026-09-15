"""Ordered health checks. The first failure is reported with its fix."""

import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from teslai.errors import CATALOG, ErrorInfo
from teslai.secrets import SecretPaths, cert_days_left, server_cert_signed_by_ca
from teslai.settings import Settings

REQUIRED = [
    "teslai_domain",
    "teslai_telemetry_host",
    "database_url",
    "teslai_session_secret",
]
PLACEHOLDERS = {"", "CHANGE_ME", "teslai.example.com", "telemetry.teslai.example.com"}


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    code: str | None = None
    skipped: bool = False

    @property
    def info(self) -> ErrorInfo | None:
        return CATALOG.get(self.code) if self.code else None


def _tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _host_port_from_db_url(url: str) -> tuple[str, int] | None:
    from sqlalchemy.engine import make_url

    try:
        u = make_url(url)
    except Exception:  # noqa: BLE001
        return None
    return (u.host or "localhost", u.port or 5432)


def run_checks(env_path: Path, settings: Settings | None = None,
               network: bool = True) -> list[CheckResult]:
    results: list[CheckResult] = []

    def add(name: str, fn: Callable[[], CheckResult]) -> bool:
        r = fn()
        results.append(r)
        return r.ok or r.skipped

    if not env_path.exists():
        results.append(CheckResult(".env present", False, str(env_path), "TSL-ENV-MISSING"))
        return results
    results.append(CheckResult(".env present", True))
    s = settings or Settings(_env_file=env_path)

    def required() -> CheckResult:
        missing = [k.upper() for k in REQUIRED if str(getattr(s, k)).strip() in PLACEHOLDERS]
        if missing:
            return CheckResult("required settings", False, ", ".join(missing),
                               "TSL-ENV-INCOMPLETE")
        return CheckResult("required settings", True)

    if not add("required settings", required):
        return results

    paths = SecretPaths(s.teslai_secrets_dir)

    def secrets_present() -> CheckResult:
        missing = [p.name for p in paths.all() if not p.exists()]
        if missing:
            return CheckResult("secrets present", False, ", ".join(missing),
                               "TSL-SECRETS-MISSING")
        return CheckResult("secrets present", True)

    if not add("secrets present", secrets_present):
        return results

    def chain() -> CheckResult:
        if not server_cert_signed_by_ca(paths):
            return CheckResult("server cert issued by private CA", False,
                               paths.server_cert.name, "TSL-CA-MISMATCH")
        return CheckResult("server cert issued by private CA", True)

    if not add("chain", chain):
        return results

    def expiry() -> CheckResult:
        days = cert_days_left(paths.server_cert)
        if days < 14:
            return CheckResult("server cert expiry", False, f"{days:.1f} days left",
                               "TSL-CERT-EXPIRING")
        return CheckResult("server cert expiry", True, f"{days:.0f} days left")

    if not add("expiry", expiry):
        return results

    if network:
        def db() -> CheckResult:
            hp = _host_port_from_db_url(s.database_url)
            if hp is None or not _tcp_reachable(*hp):
                return CheckResult("database reachable", False, str(hp), "TSL-DB-UNREACHABLE")
            return CheckResult("database reachable", True, f"{hp[0]}:{hp[1]}")

        if not add("db", db):
            return results

        def mqtt() -> CheckResult:
            if not _tcp_reachable(s.mqtt_host, s.mqtt_port):
                return CheckResult("mqtt reachable", False, f"{s.mqtt_host}:{s.mqtt_port}",
                                   "TSL-MQTT-UNREACHABLE")
            return CheckResult("mqtt reachable", True, f"{s.mqtt_host}:{s.mqtt_port}")

        if not add("mqtt", mqtt):
            return results

    def tesla() -> CheckResult:
        if not s.tesla_client_id:
            return CheckResult("tesla app configured", False, "", "TSL-TESLA-UNCONFIGURED",
                               skipped=True)
        return CheckResult("tesla app configured", True)

    add("tesla", tesla)
    return results
