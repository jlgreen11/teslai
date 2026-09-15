"""Error catalog.

Every failure an operator can hit has a stable code. `teslai doctor`, alerts,
logs and API errors all use these codes, so a message seen anywhere can be
looked up in docs/errors.md.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    problem: str
    cause: str
    fix: str

    @property
    def anchor(self) -> str:
        return f"docs/errors.md#{self.code.lower()}"


CATALOG: dict[str, ErrorInfo] = {
    e.code: e
    for e in [
        ErrorInfo(
            "TSL-ENV-MISSING",
            "No .env file was found.",
            "teslai has not been initialized in this directory.",
            "Run `teslai init --domain <your-domain>`.",
        ),
        ErrorInfo(
            "TSL-ENV-INCOMPLETE",
            "A required setting is empty.",
            "The value was never filled in, or still holds a placeholder.",
            "Edit .env and set the named variable, or re-run `teslai init --force`.",
        ),
        ErrorInfo(
            "TSL-SECRETS-MISSING",
            "The private CA, telemetry certificate or app key is missing.",
            "The secrets directory was deleted or never generated.",
            "Run `teslai init --force` to regenerate secrets, then re-push the telemetry config.",
        ),
        ErrorInfo(
            "TSL-CERT-EXPIRING",
            "The telemetry server certificate expires within 14 days.",
            "The certificate was issued long ago and has not been rotated.",
            "Run `teslai init --rotate-server-cert`, then `teslai telemetry push --reason cert-rotate`.",
        ),
        ErrorInfo(
            "TSL-CA-MISMATCH",
            "The CA in the car's telemetry config does not match the server certificate chain.",
            "The server certificate was reissued under a different CA, or Caddy's public "
            "certificate was used instead of the private CA.",
            "Run `teslai telemetry push --reason ca-fix`.",
        ),
        ErrorInfo(
            "TSL-DB-UNREACHABLE",
            "The database did not accept a connection.",
            "Postgres is not running, or DATABASE_URL is wrong.",
            "Run `docker compose up -d db` and check DATABASE_URL in .env.",
        ),
        ErrorInfo(
            "TSL-MQTT-UNREACHABLE",
            "The MQTT broker did not accept a connection.",
            "Mosquitto is not running, or MQTT_HOST/MQTT_PORT is wrong.",
            "Run `docker compose up -d mosquitto` and check MQTT_HOST and MQTT_PORT.",
        ),
        ErrorInfo(
            "TSL-TESLA-UNCONFIGURED",
            "No Tesla developer app is configured yet.",
            "TESLA_CLIENT_ID is empty.",
            "Register an app at developer.tesla.com, then run `teslai tesla register`.",
        ),
        ErrorInfo(
            "TSL-PARTNER-UNREGISTERED",
            "Tesla rejected a call because the app is not registered in this region.",
            "The partner-account registration call was never made for TESLA_REGION, or "
            "TESLA_REGION does not match where the car's account lives (HTTP 412).",
            "Run `teslai tesla register`.",
        ),
        ErrorInfo(
            "TSL-REGION-WRONG",
            "Tesla returned a region error.",
            "TESLA_REGION does not match the account's region.",
            "Set TESLA_REGION to na, eu or cn in .env, then run `teslai tesla register`.",
        ),
        ErrorInfo(
            "TSL-SCOPE-MISSING",
            "Tesla returned 403 for a field or endpoint.",
            "The owner did not grant a scope the request needs, such as vehicle location.",
            "Re-authorize with the required scopes via `teslai tesla login`.",
        ),
        ErrorInfo(
            "TSL-TOKEN-CONSUMED",
            "The Tesla refresh token was rejected.",
            "Refresh tokens are single-use; another process refreshed first, or the owner "
            "revoked access.",
            "Run `teslai tesla login` to re-authorize.",
        ),
        ErrorInfo(
            "TSL-KEY-UNPAIRED",
            "The car has not accepted teslai's virtual key.",
            "The QR pairing step was skipped or declined in the Tesla app.",
            "Run `teslai pair` and scan the QR code with the Tesla app.",
        ),
        ErrorInfo(
            "TSL-CONFIG-NULL",
            "The car reports a synced telemetry config of null.",
            "Another app's config is active on the car (fleet-telemetry issue #294).",
            "Remove the other app's config, then run `teslai telemetry push`.",
        ),
        ErrorInfo(
            "TSL-CONFIG-UNSYNCED",
            "The car has not synced the latest telemetry config.",
            "The car is asleep or offline since the config was pushed.",
            "Wake the car from the Tesla app, then run `teslai telemetry status`.",
        ),
        ErrorInfo(
            "TSL-BILLING-DISABLED",
            "Tesla disabled the app for exceeding its billing limit.",
            "Monthly Fleet API usage passed the limit set in the developer console.",
            "Raise the limit at developer.tesla.com, then lower field rates in telemetry.yaml.",
        ),
        ErrorInfo(
            "TSL-FIRMWARE-TOO-OLD",
            "The car's firmware does not support a subscribed field.",
            "Some fields need newer firmware, for example DetailedChargeState needs 2024.38.",
            "Update the car's software, or remove the field from telemetry.yaml.",
        ),
        ErrorInfo(
            "TSL-HARDWARE-UNSUPPORTED",
            "The car's hardware does not support Fleet Telemetry.",
            "Tesla skipped the car as unsupported hardware, for example some pre-2018 Model S/X.",
            "No software fix exists. The car cannot stream telemetry to teslai.",
        ),
        ErrorInfo(
            "TSL-CONFIG-EXPIRING",
            "The car's telemetry config expires within 14 days.",
            "The config was pushed with an `exp` timestamp that is approaching.",
            "Run `teslai telemetry push --yes` to push a fresh config.",
        ),
        ErrorInfo(
            "TSL-INGEST-SILENT",
            "The car reports connected but no telemetry has arrived recently.",
            "The telemetry config is unsynced, fleet-telemetry or the worker stopped, or the "
            "telemetry certificate chain changed.",
            "Run `teslai doctor` and `docker compose exec app teslai telemetry status`.",
        ),
        ErrorInfo(
            "TSL-BILLING-THRESHOLD",
            "This month's Tesla API usage passed an alert threshold of the free credit.",
            "Fields are sending more often than expected, or commands and wakes are frequent.",
            "Raise minimum_delta or interval_seconds in telemetry.yaml, then push the config.",
        ),
        ErrorInfo(
            "TSL-TOKEN-AGING",
            "The Tesla login has not been refreshed recently and may expire.",
            "Refresh tokens expire after 3 months without use.",
            "Keep `teslai monitor` running, or run `teslai tesla login` again.",
        ),
        ErrorInfo(
            "TSL-BACKUP-STALE",
            "No recent verified database backup exists.",
            "The backup service stopped, the disk is full, or the last restore check failed.",
            "Run `docker compose run --rm backup once` and `docker compose run --rm backup verify`, "
            "then check `docker compose logs backup`.",
        ),
        ErrorInfo(
            "TSL-CAR-UNLOCKED",
            "The car is parked and unlocked away from home.",
            "It was left unlocked, or walk-away door lock is off.",
            "Lock the car from the Tesla app.",
        ),
        ErrorInfo(
            "TSL-WINDOW-OPEN",
            "A window is open while the car is parked.",
            "A window was left down or vent mode is on.",
            "Close the windows from the Tesla app.",
        ),
        ErrorInfo(
            "TSL-TIRE-PRESSURE",
            "A tire pressure is outside the configured limits.",
            "A slow leak, a temperature swing, or limits in config/rules.yaml that do not fit the car.",
            "Check the tire, then adjust tire_pressure limits in config/rules.yaml if needed.",
        ),
        ErrorInfo(
            "TSL-NEW-SOFTWARE",
            "The car reports a new software version.",
            "Tesla installed an update.",
            "Nothing to do; this is a notice.",
        ),
        ErrorInfo(
            "TSL-SESSION-SUMMARY",
            "A drive or charge finished.",
            "The car completed a drive or charge that passed the summary thresholds.",
            "Nothing to do; this is a notice. Thresholds are in config/rules.yaml.",
        ),
        ErrorInfo(
            "TSL-VIN-REJECTED",
            "Telemetry arrived for a VIN that is not in the vehicles table.",
            "A car connected that this deployment does not own, or TESLA_VIN is wrong.",
            "Check TESLA_VIN in .env. Unknown VINs are dropped by design.",
        ),
        ErrorInfo(
            "TSL-IMPORT-SCHEMA",
            "A TeslaFi CSV is missing expected columns or changed units.",
            "TeslaFi changed its export format, or the file is not a TeslaFi export.",
            "Check the named file and columns; re-download the export from TeslaFi.",
        ),
        ErrorInfo(
            "TSL-IMPORT-TZ",
            "The import timezone is missing or invalid.",
            "TeslaFi timestamps have no offset, so the home timezone must be given.",
            "Pass --tz with an IANA name, for example --tz America/Chicago.",
        ),
    ]
}


class TeslaiError(Exception):
    """An operator-facing error with a catalog code."""

    def __init__(self, code: str, detail: str = ""):
        if code not in CATALOG:
            raise KeyError(f"Unknown error code {code}")
        self.info = CATALOG[code]
        self.detail = detail
        super().__init__(self.render())

    def render(self) -> str:
        i = self.info
        lines = [f"{i.code}: {i.problem}"]
        if self.detail:
            lines.append(f"  Detail: {self.detail}")
        lines += [f"  Likely cause: {i.cause}", f"  Fix: {i.fix}", f"  Docs: {i.anchor}"]
        return "\n".join(lines)
