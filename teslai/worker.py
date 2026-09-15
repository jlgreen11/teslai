"""MQTT ingest worker: fleet-telemetry messages into telemetry_events.

Topics published by fleet-telemetry's MQTT dispatcher:

    <topic_base>/<VIN>/v/<field>            payload: JSON value
    <topic_base>/<VIN>/connectivity         payload: {"ConnectionId","Status","CreatedAt"}
    <topic_base>/<VIN>/alerts/<name>/...    logged only
    <topic_base>/<VIN>/errors/<name>        logged only

Vehicle-data payloads carry no timestamp, so field events are stamped with the
time the worker received them. Connectivity records do carry CreatedAt and use it.

Delivery: QoS 1, a fixed client id with clean_session=False, and manual acks.
A message is acknowledged only after its database transaction commits, so a
crash or database error leaves it on the broker for redelivery. Because field
payloads have no timestamp, a redelivered message gets a new receive time; the
worker skips an event whose value equals the previous value for that field,
since the car only sends a field when it changes. Signals are still counted.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, text

from teslai.db import repo
from teslai.errors import TeslaiError
from teslai.reducer import Event

log = logging.getLogger("teslai.worker")

TOPIC_RE = re.compile(
    r"^(?P<base>[^/]+)/(?P<vin>[A-HJ-NPR-Z0-9]{17})/(?P<kind>v|connectivity|alerts|errors)"
    r"(?:/(?P<rest>.+))?$"
)


@dataclass(frozen=True)
class Parsed:
    vin: str
    kind: str
    ts: datetime
    field: str | None = None
    value: Any = None
    connected: bool | None = None


def _parse_ts(value: Any, fallback: datetime) -> datetime:
    if not isinstance(value, str):
        return fallback
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return fallback
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def normalize_value(value: Any) -> Any:
    """Map fleet-telemetry JSON values to what the builder expects."""
    if isinstance(value, dict):
        if value.get("invalid") is True or value.get("Invalid") is True:
            return None
        lower = {k.lower(): v for k, v in value.items()}
        if "latitude" in lower and "longitude" in lower:
            return {"latitude": float(lower["latitude"]), "longitude": float(lower["longitude"])}
    return value


def parse_message(topic: str, payload: bytes, received_at: datetime) -> Parsed | None:
    m = TOPIC_RE.match(topic)
    if not m:
        return None
    vin, kind, rest = m["vin"], m["kind"], m["rest"]
    try:
        body = json.loads(payload.decode("utf-8")) if payload else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.warning("unparseable payload on %s", topic)
        return None
    if kind == "v":
        if not rest or "/" in rest:
            return None
        return Parsed(vin, kind, received_at, field=rest, value=normalize_value(body))
    if kind == "connectivity":
        if not isinstance(body, dict):
            return None
        status = str(body.get("Status", "")).lower()
        if status not in ("connected", "disconnected"):
            return None
        return Parsed(vin, kind, _parse_ts(body.get("CreatedAt"), received_at),
                      connected=status == "connected")
    return Parsed(vin, kind, received_at, field=rest, value=body)


class Ingestor:
    def __init__(self, engine: Engine, account_id: int):
        self.engine = engine
        self.account_id = account_id
        self._vehicle_ids: dict[str, int] = {}
        self._rejected: set[str] = set()
        self._last_value: dict[tuple[int, str], Any] = {}

    def _vehicle_id(self, conn, vin: str) -> int | None:
        if vin in self._vehicle_ids:
            return self._vehicle_ids[vin]
        try:
            vid = repo.vehicle_id_for_vin(conn, self.account_id, vin)
        except TeslaiError as err:
            if vin not in self._rejected:
                log.warning("%s", err)
                self._rejected.add(vin)
            return None
        self._vehicle_ids[vin] = vid
        return vid

    def handle(self, topic: str, payload: bytes, received_at: datetime | None = None) -> bool:
        """Process one message inside one transaction. Returns True if it should be acked."""
        parsed = parse_message(topic, payload, received_at or datetime.now(UTC))
        if parsed is None:
            return True  # malformed or irrelevant: ack so it is not redelivered forever
        if parsed.kind in ("alerts", "errors"):
            log.info("%s %s: %s", parsed.kind, parsed.field, parsed.value)
            return True
        with self.engine.begin() as conn:
            vid = self._vehicle_id(conn, parsed.vin)
            if vid is None:
                return True
            if parsed.kind == "connectivity":
                repo.record_connectivity(conn, self.account_id, vid, parsed.ts, parsed.connected)
                return True
            key = (vid, parsed.field)
            if key in self._last_value and self._last_value[key] == parsed.value:
                repo.add_usage(conn, self.account_id, vid, parsed.ts.date(), "signal", 1,
                               parsed.field)
                return True
            repo.insert_events(conn, self.account_id,
                               [Event(vid, parsed.ts, parsed.field, parsed.value)])
            repo.add_usage(conn, self.account_id, vid, parsed.ts.date(), "signal", 1,
                           parsed.field)
        self._last_value[key] = parsed.value
        return True


def single_account_id(engine: Engine) -> int:
    with engine.connect() as conn:
        ids = conn.execute(text("SELECT id FROM accounts ORDER BY id LIMIT 2")).scalars().all()
    if len(ids) != 1:
        raise RuntimeError("Personal mode expects exactly one account; create it with "
                           "`teslai owner create`, `teslai tesla login` or "
                           "`teslai import teslafi --write`.")
    return ids[0]


def run(engine: Engine, host: str, port: int, topic_base: str, client_id: str = "teslai-worker",
        account_id: int | None = None,
        recordings_dir: str | None = None) -> None:  # pragma: no cover - integration
    from pathlib import Path

    import paho.mqtt.client as mqtt

    from teslai.recorder import PayloadRecorder

    ingestor = Ingestor(engine, account_id or single_account_id(engine))
    recorder = PayloadRecorder(Path(recordings_dir)) if recordings_dir else None
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                         clean_session=False, manual_ack=True)

    def on_connect(c, _userdata, _flags, reason, _props):
        log.info("connected to %s:%s (%s)", host, port, reason)
        c.subscribe([(f"{topic_base}/+/v/+", 1), (f"{topic_base}/+/connectivity", 1),
                     (f"{topic_base}/+/alerts/#", 1), (f"{topic_base}/+/errors/#", 1)])

    def on_message(c, _userdata, msg):
        received_at = datetime.now(UTC)
        try:
            if recorder is not None:
                recorder.write(msg.topic, msg.payload, received_at)
            if ingestor.handle(msg.topic, msg.payload, received_at):
                c.ack(msg.mid, msg.qos)
        except Exception:
            log.exception("failed to ingest %s; leaving unacknowledged", msg.topic)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, keepalive=30)
    client.loop_forever(retry_first_connection=True)
