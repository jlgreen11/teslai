import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from teslai.db import repo
from teslai.recorder import PayloadRecorder, read_records
from teslai.worker import Ingestor

pytestmark = pytest.mark.integration


def test_replaying_a_recording_twice_is_idempotent(engine, tmp_path):
    vin = ("REPLAY" + uuid.uuid4().hex.upper())[:17].replace("I", "1").replace("O", "0").replace("Q", "9")
    with engine.begin() as conn:
        a = repo.create_account(conn, f"owner-{vin}")
        v = repo.create_vehicle(conn, a, vin)
    t0 = datetime(2026, 9, 15, 12, tzinfo=UTC)
    rec = PayloadRecorder(tmp_path)
    rec.write(f"telemetry/{vin}/v/Gear", b'"ShiftStateD"', t0)
    rec.write(f"telemetry/{vin}/v/VehicleSpeed", b"42", t0 + timedelta(seconds=5))
    rec.write(f"telemetry/{vin}/connectivity",
              b'{"Status":"DISCONNECTED","CreatedAt":"2026-09-15T12:10:00Z"}', t0 + timedelta(minutes=10))
    for _ in range(2):
        ing = Ingestor(engine, a)
        for r in read_records([tmp_path]):
            ing.handle(r.topic, r.payload, r.received_at)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT field, ts FROM telemetry_events WHERE vehicle_id=:v ORDER BY ts"),
                            {"v": v}).all()
        conn_rows = conn.execute(text("SELECT count(*) FROM connectivity_events WHERE vehicle_id=:v"),
                                 {"v": v}).scalar()
    assert [(r.field, r.ts) for r in rows] == [("Gear", t0), ("VehicleSpeed", t0 + timedelta(seconds=5))]
    assert conn_rows == 1
