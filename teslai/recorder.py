"""Raw MQTT payload recording and replay.

The worker appends every message it receives to a daily gzip file before
processing it:

    recordings/2026-09-15.jsonl.gz
        {"t": "2026-09-15T12:00:01.123456+00:00", "topic": "...", "payload": "<base64>"}

Each append is its own gzip member, so a crash never corrupts earlier records
and gzip.open() reads the whole file. Recordings stay outside the repository
(gitignored) because they contain the car's location history.

Replay pushes records back through the same Ingestor with their original
receive times. Ingest is idempotent on (vehicle, time, field), so replaying a
day twice changes nothing.
"""

import base64
import gzip
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Record:
    received_at: datetime
    topic: str
    payload: bytes


class PayloadRecorder:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, ts: datetime) -> Path:
        return self.directory / f"{ts:%Y-%m-%d}.jsonl.gz"

    def write(self, topic: str, payload: bytes, received_at: datetime) -> None:
        line = json.dumps({"t": received_at.isoformat(), "topic": topic,
                           "payload": base64.b64encode(payload).decode()}) + "\n"
        path = self.path_for(received_at)
        with gzip.open(path, "at", encoding="utf-8") as f:
            f.write(line)
        path.chmod(0o600)


def read_records(paths: list[Path]) -> Iterator[Record]:
    files: list[Path] = []
    for p in paths:
        files.extend(sorted(p.glob("*.jsonl.gz")) if p.is_dir() else [p])
    for path in sorted(files):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for n, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    yield Record(datetime.fromisoformat(obj["t"]), obj["topic"],
                                 base64.b64decode(obj["payload"]))
                except (KeyError, ValueError) as err:
                    raise ValueError(f"{path.name} line {n}: {err}") from None
