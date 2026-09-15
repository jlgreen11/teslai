"""Chronological, file-by-file TeslaFi import through the session builder.

Files are processed one at a time in order of their first timestamp so memory
stays bounded by one month of rows, while a single SessionBuilder carries state
across file boundaries.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from teslai.builder import BuilderParams, Session, SessionBuilder
from teslai.importer.teslafi import ImportReport, read_rows, to_events


@dataclass
class ImportResult:
    sessions: list[Session]
    reports: list[ImportReport] = field(default_factory=list)
    first_ts: datetime | None = None
    last_ts: datetime | None = None


def expand_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        out.extend(sorted(p.glob("*.csv")) if p.is_dir() else [p])
    return out


def _first_ts(path: Path, tz: str) -> datetime | None:
    rows, _ = read_rows(path, tz)
    for r in rows:
        return r.ts
    return None


def import_teslafi(paths: list[Path], tz: str, vehicle_id: int = 0,
                   params: BuilderParams | None = None) -> ImportResult:
    files = expand_paths(paths)
    ordered = sorted(((ts, f) for f in files if (ts := _first_ts(f, tz)) is not None),
                     key=lambda x: x[0])
    builder = SessionBuilder(params=params)
    result = ImportResult(sessions=[])
    for _, f in ordered:
        rows, report = read_rows(f, tz)
        events, conn = to_events(list(rows), vehicle_id)
        builder.feed(events, conn)
        result.reports.append(report)
        if report.first_ts and (result.first_ts is None or report.first_ts < result.first_ts):
            result.first_ts = report.first_ts
        if report.last_ts and (result.last_ts is None or report.last_ts > result.last_ts):
            result.last_ts = report.last_ts
    if result.last_ts is not None:
        result.sessions = builder.finalize(result.last_ts)
    return result
