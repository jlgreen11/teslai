"""Session builder: turns an event stream into drives, charges, idles and sleeps.

Input is the same for live telemetry and TeslaFi history: field events plus
connectivity changes. Enum fields are converted to builder meanings first
(config/enums.yaml), then fed through the carry-forward reducer. The builder is
evaluated at every input timestamp.

    ┌──────────┐ connect        ┌────────┐ gear moving ≥ debounce   ┌─────────┐
    │ offline  │───────────────▶│ parked │ and odometer/speed moves │ driving │
    │ (sleep / │◀───────────────│ (idle) │─────────────────────────▶│         │
    │ unreach.)│  disconnect    └────────┘◀─────────────────────────└─────────┘
    └──────────┘                  │    ▲   park ≥ dwell, or offline ≥ offline_end
                   charge=charging│    │complete/stopped/disconnected
                                  ▼    │
                               ┌──────────┐  energy counter reset: close and reopen
                               │ charging │───┐
                               └──────────┘◀──┘

Sleep versus unreachable is decided by overlap with known server downtime,
never by silence alone. Rebuilding from the same inputs in any order gives the
same sessions.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import groupby
from typing import Literal

from teslai.config import EnumTable, FieldSpec, default_enum_table, default_field_specs
from teslai.reducer import Event, StateReducer

SessionKind = Literal["drive", "charge", "idle", "sleep", "unreachable"]
ENUM_FIELDS = ("Gear", "DetailedChargeState", "ChargingCableType")
MOVING = {"drive", "reverse", "neutral"}
CHARGE_ENDED = {"complete", "stopped", "disconnected", "plugged_idle"}


@dataclass(frozen=True)
class BuilderParams:
    version: int = 1
    drive_debounce_s: int = 10
    park_dwell_s: int = 60
    offline_end_drive_s: int = 600
    min_drive_miles: float = 0.05
    counter_reset_kwh: float = 0.05


@dataclass
class Session:
    kind: SessionKind
    start: datetime
    end: datetime | None = None
    start_odometer: float | None = None
    end_odometer: float | None = None
    start_battery: float | None = None
    end_battery: float | None = None
    energy_added_kwh: float | None = None
    charger: Literal["ac", "dc"] | None = None
    flags: set[str] = field(default_factory=set)
    start_location: dict | None = None
    end_location: dict | None = None
    end_rated_range: float | None = None

    @property
    def distance(self) -> float | None:
        if self.start_odometer is None or self.end_odometer is None:
            return None
        return self.end_odometer - self.start_odometer


@dataclass(frozen=True)
class Connectivity:
    ts: datetime
    connected: bool


def _enum_source(event_source: str) -> str:
    return "teslafi" if event_source.startswith("teslafi") else "telemetry"


class SessionBuilder:
    def __init__(self, params: BuilderParams | None = None,
                 specs: dict[str, FieldSpec] | None = None,
                 enums: EnumTable | None = None,
                 server_downtime: Sequence[tuple[datetime, datetime]] = ()):
        self.p = params or BuilderParams()
        self.enums = enums or default_enum_table()
        self.r = StateReducer(specs or default_field_specs())
        self.downtime = list(server_downtime)
        self.sessions: list[Session] = []
        self.current: Session | None = None
        self.connected: bool | None = None
        self.offline_since: datetime | None = None
        self.pending_drive: datetime | None = None
        self.pending_odometer: float | None = None
        self.park_since: datetime | None = None
        self.charge_counter_start: dict[str, float] = {}
        self.charge_counter_max: dict[str, float] = {}

    # ---- helpers -------------------------------------------------------------
    def _v(self, at: datetime, name: str):
        return self.r.value(at, name)

    def _last(self, at: datetime, name: str):
        return self.r.last_known(at, name)

    def _open(self, kind: SessionKind, at: datetime) -> None:
        s = Session(kind, at, start_odometer=self._last(at, "Odometer"),
                    start_battery=self._last(at, "BatteryLevel"),
                    start_location=self._last(at, "Location"))
        if kind == "charge":
            self.charge_counter_start = {
                k: self._last(at, f) or 0.0
                for k, f in (("ac", "ACChargingEnergyIn"), ("dc", "DCChargingEnergyIn"))
            }
            self.charge_counter_max = dict(self.charge_counter_start)
        self.current = s

    def _close(self, at: datetime, flag: str | None = None) -> None:
        s = self.current
        if s is None:
            return
        s.end = at
        s.end_odometer = self._last(at, "Odometer")
        s.end_battery = self._last(at, "BatteryLevel")
        s.end_location = self._last(at, "Location")
        s.end_rated_range = self._last(at, "RatedRange")
        if flag:
            s.flags.add(flag)
        if s.kind == "charge":
            gains = {k: self.charge_counter_max[k] - self.charge_counter_start[k]
                     for k in ("ac", "dc")}
            s.charger = "dc" if gains["dc"] > gains["ac"] else "ac"
            s.energy_added_kwh = round(max(gains.values()), 3)
        if s.kind == "drive" and s.distance is not None and s.distance < self.p.min_drive_miles:
            s.flags.add("short")
        if s.end > s.start or s.kind in ("drive", "charge"):
            self.sessions.append(s)
        self.current = None

    def _offline_kind(self, start: datetime, end: datetime | None) -> SessionKind:
        stop = end or start
        for d0, d1 in self.downtime:
            if d0 < stop and start < d1 or d0 <= start <= d1:
                return "unreachable"
        return "sleep"

    # ---- input ---------------------------------------------------------------
    def feed(self, events: Iterable[Event], connectivity: Iterable[Connectivity]) -> None:
        items: list[tuple[datetime, int, str, object]] = []
        for c in connectivity:
            items.append((c.ts, 0 if c.connected else 2, "c", c))
        for e in events:
            if e.field in ENUM_FIELDS:
                e = Event(e.vehicle_id, e.ts, e.field,
                          self.enums.meaning(e.field, e.value, _enum_source(e.source)), e.source)
            items.append((e.ts, 1, e.field, e))
        items.sort(key=lambda i: (i[0], i[1], i[2], repr(getattr(i[3], "value", ""))))
        for ts, group in groupby(items, key=lambda i: i[0]):
            group = list(group)
            for _, order, _, item in group:
                if order == 1:
                    self.r.apply(item)  # type: ignore[arg-type]
            for _, order, _, item in group:
                if order == 0:
                    self._connectivity(item)  # type: ignore[arg-type]
            self._evaluate(ts)
            disconnects = [item for _, order, _, item in group if order == 2]
            for item in disconnects:
                self._connectivity(item)  # type: ignore[arg-type]
            if disconnects:
                self._evaluate(ts)

    def finalize(self, at: datetime) -> list[Session]:
        """Evaluate up to `at`. Sessions still in progress stay open (end=None)."""
        self._evaluate(at)
        return self.sessions + ([self.current] if self.current else [])

    # ---- state machine -------------------------------------------------------
    def _connectivity(self, c: Connectivity) -> None:
        if c.connected:
            if self.connected is True:
                return
            self.connected = True
            if self.current and self.current.kind == "drive" and self.offline_since:
                if c.ts - self.offline_since >= timedelta(seconds=self.p.offline_end_drive_s):
                    self._close(self.offline_since, "ended_offline")
                    self._open(self._offline_kind(self.offline_since, c.ts), self.offline_since)
                    self._close(c.ts)
                    self._open("idle", c.ts)
                self.offline_since = None
                return
            if self.current and self.current.kind in ("sleep", "unreachable"):
                self.current.kind = self._offline_kind(self.current.start, c.ts)
                self._close(c.ts)
            if self.current is None:
                self._open("idle", c.ts)
            self.offline_since = None
        else:
            if self.connected is False:
                return
            self.connected = False
            self.pending_drive = None
            if self.current and self.current.kind == "drive" and self.park_since is not None:
                # The car parked and then went offline: the park was final.
                park = self.park_since
                self._close(park)
                self._open("idle", park)
            self.park_since = None
            self.r.connectivity(c.ts, connected=False)
            if self.current and self.current.kind == "drive":
                self.offline_since = c.ts
                return
            self._close(c.ts)
            self._open(self._offline_kind(c.ts, None), c.ts)

    def _evaluate(self, at: datetime) -> None:
        """Step the state machine until it settles, so one timestamp can end a drive
        and start a charge."""
        for _ in range(4):
            before = (self.current.kind if self.current else None,
                      self.current.start if self.current else None)
            self._step(at)
            after = (self.current.kind if self.current else None,
                     self.current.start if self.current else None)
            if after == before:
                return

    def _step(self, at: datetime) -> None:
        if not self.connected:
            s = self.current
            if (s and s.kind == "drive" and self.offline_since
                    and at - self.offline_since >= timedelta(seconds=self.p.offline_end_drive_s)):
                off = self.offline_since
                self._close(off, "ended_offline")
                self._open(self._offline_kind(off, None), off)
                self.offline_since = None
            return

        gear = self._v(at, "Gear")
        charge = self._v(at, "DetailedChargeState")
        speed = self._v(at, "VehicleSpeed")
        odometer = self._last(at, "Odometer")
        kind = self.current.kind if self.current else None

        if kind != "drive":
            if gear in MOVING:
                if self.pending_drive is None:
                    self.pending_drive, self.pending_odometer = at, odometer
                moved = (odometer is not None and self.pending_odometer is not None
                         and odometer > self.pending_odometer) or (speed or 0) > 0
                if at - self.pending_drive >= timedelta(seconds=self.p.drive_debounce_s) and moved:
                    start = self.pending_drive
                    self._close(start)
                    self._open("drive", start)
                    self.current.start_odometer = self.pending_odometer  # type: ignore[union-attr]
                    self.pending_drive = None
                    self.park_since = None
                    return
            else:
                self.pending_drive = None

        if kind == "drive":
            if gear == "park":
                self.park_since = self.park_since or at
                if at - self.park_since >= timedelta(seconds=self.p.park_dwell_s):
                    end = self.park_since
                    self._close(end)
                    self._open("idle", end)
                    self.park_since = None
            elif gear in MOVING:
                self.park_since = None
            return

        if kind in ("idle", None) and charge == "charging":
            self._close(at)
            self._open("charge", at)
            return

        if kind == "charge":
            for k, f in (("ac", "ACChargingEnergyIn"), ("dc", "DCChargingEnergyIn")):
                val = self._last(at, f)
                if val is None:
                    continue
                no_gain_yet = self.charge_counter_max[k] <= self.charge_counter_start[k]
                if val < self.charge_counter_max[k] - self.p.counter_reset_kwh and no_gain_yet:
                    # The car reset its counter as this charge began; rebase.
                    self.charge_counter_start[k] = val
                    self.charge_counter_max[k] = val
                    continue
                if val < self.charge_counter_max[k] - self.p.counter_reset_kwh:
                    self._close(at, "counter_reset")
                    self._open("charge", at)
                    self.charge_counter_start[k] = val
                    self.charge_counter_max[k] = val
                    return
                self.charge_counter_max[k] = max(self.charge_counter_max[k], val)
            if charge in CHARGE_ENDED:
                self._close(at)
                self._open("idle", at)


def build_sessions(events: Iterable[Event], connectivity: Iterable[Connectivity], until: datetime,
                   **kwargs) -> list[Session]:
    b = SessionBuilder(**kwargs)
    b.feed(events, connectivity)
    return b.finalize(until)
