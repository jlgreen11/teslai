"""Car-state alert rules.

    telemetry_events (last 24 h) + connectivity ──▶ reducer ──▶ last known state
                                                                     │
         places of kind "home" ─────────────────────────────────────┤
                                                                     ▼
        unlocked_away   Locked is false, parked, not at home, for ≥ N minutes
        windows_open    any window not closed, parked, for ≥ N minutes
        tire_pressure   any tire below low_bar or above high_bar
        new_software    a Version the owner has not been told about (informational)

State fields keep their last value while the car sleeps (a car can sleep
unlocked), so these rules read last-known values, not only currently valid ones.
Window value names are not documented; any value outside CLOSED_WINDOW counts as open.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from teslai.alerts import Condition
from teslai.config import default_enum_table, default_field_specs
from teslai.paths import CONFIG_DIR
from teslai.places import Place, match_place
from teslai.reducer import FieldValue

WINDOW_FIELDS = ("FdWindow", "FpWindow", "RdWindow", "RpWindow")
TIRE_FIELDS = {"TpmsPressureFl": "front left", "TpmsPressureFr": "front right",
               "TpmsPressureRl": "rear left", "TpmsPressureRr": "rear right"}
CLOSED_WINDOW = {"WindowStateClosed", "Closed", "closed", 0, "0"}


@dataclass(frozen=True)
class RuleConfig:
    unlocked_enabled: bool = True
    unlocked_minutes: int = 10
    windows_enabled: bool = True
    windows_minutes: int = 10
    tires_enabled: bool = True
    tire_low_bar: float = 2.6
    tire_high_bar: float = 3.5
    software_enabled: bool = True
    summaries_enabled: bool = True
    summary_drive_min_miles: float = 1.0
    summary_charge_min_kwh: float = 1.0


def load_rule_config(path: Path | None = None) -> RuleConfig:
    if path is None:
        path = CONFIG_DIR / "rules.yaml"
        if not path.exists():
            path = CONFIG_DIR / "rules.example.yaml"
    raw = yaml.safe_load(path.read_text()) or {}
    u, w = raw.get("unlocked_away") or {}, raw.get("windows_open") or {}
    t, s = raw.get("tire_pressure") or {}, raw.get("new_software") or {}
    m = raw.get("session_summaries") or {}
    cfg = RuleConfig(
        unlocked_enabled=bool(u.get("enabled", True)), unlocked_minutes=int(u.get("minutes", 10)),
        windows_enabled=bool(w.get("enabled", True)), windows_minutes=int(w.get("minutes", 10)),
        tires_enabled=bool(t.get("enabled", True)), tire_low_bar=float(t.get("low_bar", 2.6)),
        tire_high_bar=float(t.get("high_bar", 3.5)), software_enabled=bool(s.get("enabled", True)),
        summaries_enabled=bool(m.get("enabled", True)),
        summary_drive_min_miles=float(m.get("drive_min_miles", 1.0)),
        summary_charge_min_kwh=float(m.get("charge_min_kwh", 1.0)))
    if cfg.tire_low_bar >= cfg.tire_high_bar:
        raise ValueError("tire_pressure.low_bar must be below high_bar")
    return cfg


def _since(fv: FieldValue | None, now: datetime) -> timedelta:
    return now - fv.ts if fv else timedelta(0)


def evaluate(vehicle_id: int, last4: str, state: dict[str, FieldValue], connected: bool,
             now: datetime, home_places: list[Place], cfg: RuleConfig) -> list[Condition]:
    enums = default_enum_table()
    out: list[Condition] = []
    gear = state.get("Gear")
    gear_meaning = enums.meaning("Gear", gear.value) if gear else "unknown"
    parked = (not connected) or gear_meaning == "park"
    car = f"car ···{last4}"

    locked = state.get("Locked")
    if cfg.unlocked_enabled and parked and locked is not None and locked.value is False:
        location = state.get("Location")
        at_home = match_place(location.value if location else None, home_places) is not None
        if not at_home and _since(locked, now) >= timedelta(minutes=cfg.unlocked_minutes):
            minutes = int(_since(locked, now).total_seconds() // 60)
            out.append(Condition("unlocked_away", str(vehicle_id), "TSL-CAR-UNLOCKED",
                                 f"{car} unlocked away from home for {minutes} min"))

    if cfg.windows_enabled and parked:
        open_windows = [f for f in WINDOW_FIELDS
                        if state.get(f) is not None and state[f].value not in CLOSED_WINDOW
                        and _since(state[f], now) >= timedelta(minutes=cfg.windows_minutes)]
        if open_windows:
            out.append(Condition("windows_open", str(vehicle_id), "TSL-WINDOW-OPEN",
                                 f"{car} window open while parked: {', '.join(open_windows)}"))

    if cfg.tires_enabled:
        for field, name in TIRE_FIELDS.items():
            fv = state.get(field)
            if fv is None or not isinstance(fv.value, int | float):
                continue
            if fv.value < cfg.tire_low_bar or fv.value > cfg.tire_high_bar:
                out.append(Condition("tire_pressure", f"{vehicle_id}:{field}", "TSL-TIRE-PRESSURE",
                                     f"{car} {name} tire at {fv.value:.2f} bar "
                                     f"(limits {cfg.tire_low_bar}-{cfg.tire_high_bar})"))

    version = state.get("Version")
    if cfg.software_enabled and version is not None and version.value:
        out.append(Condition("new_software", f"{vehicle_id}:{version.value}", "TSL-NEW-SOFTWARE",
                             f"{car} is running software {version.value}", informational=True))
    return out


def vehicle_states(conn, account_id: int, now: datetime, lookback: timedelta = timedelta(hours=24)):
    """Yield (vehicle_id, last4, state, connected) for every vehicle in the account."""
    from sqlalchemy import text

    from teslai.db import repo
    from teslai.reducer import StateReducer

    vehicles = conn.execute(text("SELECT id, right(vin, 4) AS last4 FROM vehicles WHERE account_id = :a"),
                            {"a": account_id}).all()
    for v in vehicles:
        reducer = StateReducer(default_field_specs(), history_seconds=int(lookback.total_seconds()))
        for e in repo.events_for_vehicle(conn, account_id, v.id, now - lookback, now + timedelta(seconds=1)):
            reducer.apply(e)
        last = conn.execute(text("SELECT connected FROM connectivity_events WHERE vehicle_id = :v "
                                 "ORDER BY ts DESC LIMIT 1"), {"v": v.id}).scalar()
        snapshot = reducer.snapshot(now)
        yield v.id, v.last4, snapshot, bool(last)
