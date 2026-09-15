import os
import threading
import time
import uuid
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
import pytest
from sqlalchemy import text

from teslai.db import repo
from teslai.worker import Ingestor

pytestmark = pytest.mark.integration
MQTT_HOST = os.environ.get("TESLAI_TEST_MQTT_HOST")


def _vin():
    return ("TEST" + uuid.uuid4().hex.upper())[:17].replace("I", "1").replace("O", "0").replace("Q", "9")


def test_ingestor_writes_events_connectivity_usage_and_rejects_unknown_vin(engine):
    vin = _vin()
    with engine.begin() as conn:
        a = repo.create_account(conn, f"owner-{vin}")
        v = repo.create_vehicle(conn, a, vin)
    ing = Ingestor(engine, a)
    t = datetime(2026, 9, 15, 12, tzinfo=UTC)
    assert ing.handle(f"telemetry/{vin}/v/Gear", b'"ShiftStateD"', t)
    assert ing.handle(f"telemetry/{vin}/v/Gear", b'"ShiftStateD"', t.replace(second=5))
    assert ing.handle(f"telemetry/{vin}/v/BatteryLevel", b"70.5", t)
    assert ing.handle(f"telemetry/{vin}/connectivity",
                      b'{"Status":"CONNECTED","CreatedAt":"2026-09-15T11:59:00Z"}', t)
    assert ing.handle(f"telemetry/{_vin()}/v/Gear", b'"ShiftStateP"', t)
    with engine.connect() as conn:
        fields = conn.execute(text("SELECT field FROM telemetry_events WHERE vehicle_id=:v "
                                   "ORDER BY field"), {"v": v}).scalars().all()
        assert fields == ["BatteryLevel", "Gear"]
        assert conn.execute(text("SELECT connected FROM connectivity_events WHERE vehicle_id=:v"),
                            {"v": v}).scalar() is True
        gear_signals = conn.execute(text("SELECT count FROM api_usage WHERE vehicle_id=:v "
                                         "AND field='Gear'"), {"v": v}).scalar()
        assert gear_signals == 2


@pytest.mark.skipif(not MQTT_HOST, reason="TESLAI_TEST_MQTT_HOST not set")
def test_worker_consumes_from_broker_end_to_end(engine):
    from teslai import worker

    vin = _vin()
    with engine.begin() as conn:
        a = repo.create_account(conn, f"owner-{vin}")
        v = repo.create_vehicle(conn, a, vin)
    base = f"t{uuid.uuid4().hex[:8]}"
    th = threading.Thread(target=worker.run, daemon=True,
                          kwargs={"engine": engine, "host": MQTT_HOST, "port": 1883,
                                  "topic_base": base, "client_id": f"w-{base}", "account_id": a})
    th.start()
    time.sleep(1.0)
    pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"p-{base}")
    pub.connect(MQTT_HOST, 1883)
    pub.loop_start()
    for topic, payload in [(f"{base}/{vin}/v/Odometer", b"31000.5"),
                           (f"{base}/{vin}/v/Gear", b'"ShiftStateP"'),
                           (f"{base}/{vin}/connectivity",
                            b'{"Status":"CONNECTED","CreatedAt":"2026-09-15T12:00:00Z"}')]:
        pub.publish(topic, payload, qos=1).wait_for_publish(5)
    deadline = time.time() + 10
    n = 0
    while time.time() < deadline:
        with engine.connect() as conn:
            n = conn.execute(text("SELECT count(*) FROM telemetry_events WHERE vehicle_id=:v"),
                             {"v": v}).scalar()
            c = conn.execute(text("SELECT count(*) FROM connectivity_events WHERE vehicle_id=:v"),
                             {"v": v}).scalar()
        if n == 2 and c == 1:
            break
        time.sleep(0.2)
    pub.loop_stop()
    assert n == 2 and c == 1
