"""Carry-forward state reducer.

Fleet Telemetry sends a field only when it changes. The reducer turns that stream
of sparse events into the state at any recent moment, which the session builder
needs because it often closes a session retroactively (for example at the moment
the car parked, after later events have already arrived).

    events (any order, possibly duplicated)
        │  apply(): insert into a short per-field history, ordered by vehicle time
        ▼
    per-field history  +  disconnect timeline  +  session-boundary timeline
        │
        ▼  snapshot(at) / value(at, field)
    newest value with ts <= at, marked invalid when:
        any field:          a disconnect happened between the value and `at`
        state field:        a session boundary (reset) happened between them
        continuous field:   stale_after_seconds passed since the value

Applying the same event twice, or events out of order, gives the same answers.
History older than `history_seconds` behind the newest event is pruned, always
keeping the last value before the cutoff so carry-forward still works.
"""

from bisect import bisect_right, insort
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from teslai.config import FieldSpec


@dataclass(frozen=True)
class Event:
    vehicle_id: int
    ts: datetime
    field: str
    value: Any
    source: str = "telemetry"


@dataclass(frozen=True)
class FieldValue:
    value: Any
    ts: datetime
    valid: bool = True


def _between(timeline: list[datetime], start: datetime, end: datetime) -> bool:
    """True if any timeline instant t satisfies start <= t <= end."""
    i = bisect_right(timeline, end)
    return i > 0 and timeline[i - 1] >= start


class StateReducer:
    def __init__(self, specs: dict[str, FieldSpec], history_seconds: int = 6 * 3600):
        self._specs = specs
        self._history: dict[str, list[tuple[datetime, Any]]] = {}
        self._disconnects: list[datetime] = []
        self._resets: list[datetime] = []
        self._horizon = timedelta(seconds=history_seconds)
        self.unknown_fields: set[str] = set()

    def apply(self, event: Event) -> bool:
        """Record one event. Returns True if it was new."""
        if event.field not in self._specs:
            self.unknown_fields.add(event.field)
            return False
        hist = self._history.setdefault(event.field, [])
        i = bisect_right(hist, event.ts, key=lambda h: h[0])
        if i > 0 and hist[i - 1][0] == event.ts:
            return False
        hist.insert(i, (event.ts, event.value))
        self._prune(hist)
        return True

    def _prune(self, hist: list[tuple[datetime, Any]]) -> None:
        cutoff = hist[-1][0] - self._horizon
        keep_from = bisect_right(hist, cutoff, key=lambda h: h[0]) - 1
        if keep_from > 0:
            del hist[:keep_from]

    def connectivity(self, ts: datetime, connected: bool) -> None:
        """Record a connectivity change. Disconnects invalidate earlier values."""
        if not connected and ts not in self._disconnects:
            insort(self._disconnects, ts)

    def reset(self, ts: datetime) -> None:
        """Session boundary: state fields set before `ts` become invalid after it."""
        if ts not in self._resets:
            insort(self._resets, ts)

    def _at(self, name: str, at: datetime) -> FieldValue | None:
        hist = self._history.get(name)
        if not hist:
            return None
        i = bisect_right(hist, at, key=lambda h: h[0])
        if i == 0:
            return None
        ts, value = hist[i - 1]
        spec = self._specs[name]
        valid = not _between(self._disconnects, ts, at)
        if valid and spec.kind == "state":
            valid = not _between(self._resets, ts, at)
        if (valid and spec.kind == "continuous" and spec.stale_after_seconds is not None
                and at - ts > timedelta(seconds=spec.stale_after_seconds)):
            valid = False
        return FieldValue(value, ts, valid)

    def snapshot(self, at: datetime) -> dict[str, FieldValue]:
        out = {}
        for name in self._history:
            fv = self._at(name, at)
            if fv is not None:
                out[name] = fv
        return out

    def value(self, at: datetime, field: str) -> Any:
        """The field's value at `at`, or None if unknown or invalid."""
        fv = self._at(field, at)
        return fv.value if fv is not None and fv.valid else None

    def last_known(self, at: datetime, field: str) -> Any:
        """The field's most recent value at `at`, even if no longer valid."""
        fv = self._at(field, at)
        return fv.value if fv is not None else None
