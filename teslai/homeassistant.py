"""Home Assistant integration through MQTT discovery.

The monitor publishes, per vehicle, retained messages that Home Assistant's MQTT
integration discovers automatically:

    homeassistant/sensor/teslai_<vin>/<object>/config   discovery config (retained)
    teslai/<vin>/state                                    JSON state (retained)

Only values teslai already stores are published: battery level, rated range,
odometer, charging state, locked, last drive miles, today's miles and kWh added.
Location is not published, to keep it off the local network bus by default.
"""

import json
from dataclasses import dataclass

DISCOVERY_PREFIX = "homeassistant"


@dataclass(frozen=True)
class Entity:
    object_id: str
    name: str
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    component: str = "sensor"


ENTITIES = [
    Entity("battery_level", "Battery", "%", "battery", "measurement"),
    Entity("rated_range", "Rated range", "mi", "distance", "measurement"),
    Entity("odometer", "Odometer", "mi", "distance", "total_increasing"),
    Entity("charging_state", "Charging state"),
    Entity("locked", "Locked", component="binary_sensor", device_class="lock"),
    Entity("last_drive_miles", "Last drive", "mi", "distance"),
    Entity("today_miles", "Miles today", "mi", "distance", "total"),
    Entity("today_kwh_added", "Energy added today", "kWh", "energy", "total"),
]


def state_topic(vin: str) -> str:
    return f"teslai/{vin.lower()}/state"


def discovery_messages(vin: str, name: str) -> list[tuple[str, str]]:
    uid = f"teslai_{vin.lower()}"
    device = {"identifiers": [uid], "name": name or f"Tesla ···{vin[-4:]}", "manufacturer": "Tesla",
              "via_device": "teslai"}
    out = []
    for e in ENTITIES:
        cfg = {"name": e.name, "unique_id": f"{uid}_{e.object_id}", "state_topic": state_topic(vin),
               "value_template": f"{{{{ value_json.{e.object_id} }}}}", "device": device}
        if e.unit:
            cfg["unit_of_measurement"] = e.unit
        if e.device_class:
            cfg["device_class"] = e.device_class
        if e.state_class:
            cfg["state_class"] = e.state_class
        if e.component == "binary_sensor":
            # Home Assistant's lock device class treats "on" as unlocked.
            cfg["value_template"] = "{{ 'OFF' if value_json.locked else 'ON' }}"
        out.append((f"{DISCOVERY_PREFIX}/{e.component}/{uid}/{e.object_id}/config", json.dumps(cfg)))
    return out


def state_payload(state: dict, sessions_today: list[dict], last_drive: dict | None) -> str:
    def val(field):
        fv = state.get(field)
        return None if fv is None else fv.value

    miles = sum((s["end_odometer"] or 0) - (s["start_odometer"] or 0) for s in sessions_today
                if s["kind"] == "drive" and s["start_odometer"] is not None and s["end_odometer"] is not None
                and "short" not in (s.get("flags") or []))
    kwh = sum(s["energy_added_kwh"] or 0 for s in sessions_today if s["kind"] == "charge")
    last = None
    if last_drive and last_drive["start_odometer"] is not None and last_drive["end_odometer"] is not None:
        last = round(last_drive["end_odometer"] - last_drive["start_odometer"], 1)
    battery = val("BatteryLevel")
    return json.dumps({
        "battery_level": None if battery is None else round(float(battery), 1),
        "rated_range": val("RatedRange"),
        "odometer": val("Odometer"),
        "charging_state": val("DetailedChargeState"),
        "locked": val("Locked"),
        "last_drive_miles": last,
        "today_miles": round(miles, 1),
        "today_kwh_added": round(kwh, 2),
    })


def publish_all(engine, account_id: int, publish, now) -> int:  # pragma: no cover - integration
    """publish(topic, payload, retain) for every vehicle. Returns vehicles published."""
    from sqlalchemy import text

    from teslai.days import day_window
    from teslai.db import repo
    from teslai.rules import vehicle_states

    count = 0
    with engine.connect() as conn:
        names = {r.id: (r.vin, r.display_name, r.timezone) for r in conn.execute(text(
            "SELECT id, vin, display_name, timezone FROM vehicles WHERE account_id = :a"), {"a": account_id})}
        for vid, _last4, state, _connected in vehicle_states(conn, account_id, now):
            vin, display, tzname = names[vid]
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(tzname)
            start, end = day_window(now.astimezone(tz).date(), tz)
            today = repo.sessions_between(conn, account_id, vid, start, end)
            drives = [s for s in repo.sessions_between(conn, account_id, vid, now - __import__("datetime").timedelta(days=30), now, kind="drive") if s["end_ts"]]
            for topic, payload in discovery_messages(vin, display):
                publish(topic, payload, True)
            publish(state_topic(vin), state_payload(state, today, drives[-1] if drives else None), True)
            count += 1
    return count
