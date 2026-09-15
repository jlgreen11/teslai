import gzip
from datetime import UTC, datetime, timedelta

import pytest

from teslai.recorder import PayloadRecorder, read_records

T = datetime(2026, 9, 15, 23, 59, 59, tzinfo=UTC)


def test_roundtrip_across_days_and_reopens(tmp_path):
    rec = PayloadRecorder(tmp_path / "rec")
    rec.write("telemetry/VIN/v/Gear", b'"ShiftStateD"', T)
    rec.write("telemetry/VIN/v/Speed", b"\x00\xffbinary", T)
    rec2 = PayloadRecorder(tmp_path / "rec")
    rec2.write("telemetry/VIN/connectivity", b'{"Status":"CONNECTED"}', T + timedelta(seconds=2))
    files = sorted((tmp_path / "rec").iterdir())
    assert [f.name for f in files] == ["2026-09-15.jsonl.gz", "2026-09-16.jsonl.gz"]
    assert oct(files[0].stat().st_mode)[-3:] == "600"
    got = list(read_records([tmp_path / "rec"]))
    assert [r.topic for r in got] == ["telemetry/VIN/v/Gear", "telemetry/VIN/v/Speed",
                                      "telemetry/VIN/connectivity"]
    assert got[1].payload == b"\x00\xffbinary" and got[0].received_at == T


def test_truncated_final_member_after_crash_keeps_earlier_records(tmp_path):
    rec = PayloadRecorder(tmp_path)
    rec.write("a", b"1", T)
    rec.write("b", b"2", T)
    path = rec.path_for(T)
    data = path.read_bytes()
    with gzip.open(tmp_path / "partial.gz", "wb") as f:
        f.write(b'{"t": "2026')
    path.write_bytes(data + (tmp_path / "partial.gz").read_bytes()[:12])
    got = []
    with pytest.raises((EOFError, ValueError, OSError)):
        for r in read_records([path]):
            got.append(r.topic)
    assert got == ["a", "b"]
