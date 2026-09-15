"""Carry-forward state reducer.

Fleet Telemetry sends a field only when it changes. The reducer turns that stream
of sparse events into complete snapshots the session builder can read.

    events (any order, possibly duplicated)
        │  apply(): keep the newest value per field by vehicle timestamp
        ▼
    field table ──connectivity(disconnected)──▶ every field marked invalid
        │
        ▼  snapshot(at)
    {field: FieldValue(value, ts, valid)}
        state fields:       valid until a disconnect or reset()
        continuous fields:  valid until a disconnect, or until stale_after_seconds
                            passes without an update while connected

Applying the same event twice, or an older event after a newer one, does not
change the result. That makes replay and late delivery safe.
"""

from dataclasses import dataclass, replace
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


class StateReducer:
    def __init__(self, specs: dict[str, FieldSpec]):
        self._specs = specs
        self._fields: dict[str, FieldValue] = {}
        self._invalidated_at: datetime | None = None
        self.unknown_fields: set[str] = set()

    def apply(self, event: Event) -> bool:
        """Apply one event. Returns True if the stored value changed."""
        if event.field not in self._specs:
            self.unknown_fields.add(event.field)
            return False
        if self._invalidated_at is not None and event.ts <= self._invalidated_at:
            return False
        current = self._fields.get(event.field)
        if current is not None and current.ts >= event.ts:
            return False
        self._fields[event.field] = FieldValue(event.value, event.ts, True)
        return True

    def connectivity(self, ts: datetime, connected: bool) -> None:
        """Record a connectivity change. A disconnect invalidates every field."""
        if connected:
            return
        if self._invalidated_at is not None and ts <= self._invalidated_at:
            return
        self._invalidated_at = ts
        self._fields = {
            name: replace(fv, valid=False) if fv.ts <= ts else fv
            for name, fv in self._fields.items()
        }

    def reset(self, ts: datetime) -> None:
        """Session boundary: invalidate state fields only."""
        self._fields = {
            name: replace(fv, valid=False)
            if self._specs[name].kind == "state" and fv.ts <= ts
            else fv
            for name, fv in self._fields.items()
        }

    def snapshot(self, at: datetime) -> dict[str, FieldValue]:
        out: dict[str, FieldValue] = {}
        for name, fv in self._fields.items():
            if fv.ts > at:
                continue
            spec = self._specs[name]
            valid = fv.valid
            if (
                valid
                and spec.kind == "continuous"
                and spec.stale_after_seconds is not None
                and at - fv.ts > timedelta(seconds=spec.stale_after_seconds)
            ):
                valid = False
            out[name] = replace(fv, valid=valid)
        return out

    def value(self, at: datetime, field: str) -> Any:
        """The field's value at `at`, or None if unknown or invalid."""
        fv = self.snapshot(at).get(field)
        return fv.value if fv is not None and fv.valid else None
