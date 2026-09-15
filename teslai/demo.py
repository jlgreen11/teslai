"""Synthetic demo history for trying teslai without a car.

Generates realistic TeslaFi-style rows for a fictional car around a fictional
home in Austin, Texas: weekday commutes, weekend errands, an occasional road
trip with Supercharger stops, nightly home charging, sleep, seasonal outside
temperature, cabin climate, slow battery degradation, tire pressure that follows
temperature with an occasional slow leak, and periodic software updates.
Nothing here is real data.
"""

import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from teslai.importer.teslafi import ImportedRow
from teslai.places import Place

TZ = ZoneInfo("America/Chicago")
HOME = (30.2849, -97.7341)
PLACES = [
    Place("Home", "home", 30.2849, -97.7341, 80),
    Place("Office", "work", 30.2672, -97.7431, 150),
    Place("Grocery", "other", 30.3072, -97.7555, 120),
    Place("Climbing gym", "other", 30.2459, -97.7672, 120),
    Place("Round Rock Supercharger", "supercharger", 30.5083, -97.6789, 150),
    Place("Waco Supercharger", "supercharger", 31.5493, -97.1467, 150),
]
DESTINATIONS = {p.name: (p.latitude, p.longitude) for p in PLACES}
PACK_KWH = 75.0
FULL_RANGE_NEW = 310.0
WH_PER_MILE = 255.0
STEP = timedelta(seconds=30)


@dataclass
class CarState:
    odometer: float = 18_240.0
    battery: float = 78.0
    version: str = "2026.8.6"
    leak_until: date | None = None


def _haversine_miles(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def _outside_c(ts: datetime) -> float:
    local = ts.astimezone(TZ)
    seasonal = 20.5 - 9.5 * math.cos(2 * math.pi * (local.timetuple().tm_yday - 15) / 365)
    daily = 5.5 * math.sin(2 * math.pi * (local.hour + local.minute / 60 - 9) / 24)
    return round(seasonal + daily, 1)


def _range_at_100(day_index: int) -> float:
    return FULL_RANGE_NEW * (1 - 0.00005 * day_index)


class DemoGenerator:
    def __init__(self, start: date, days: int, seed: int = 7):
        self.start, self.days = start, days
        self.rng = random.Random(seed)
        self.car = CarState()
        self.rows: list[ImportedRow] = []
        self.line = 0

    def _row(self, ts: datetime, state: str, loc, speed=0.0, gear="P", charging="Disconnected",
             charger_power=None, energy_added=None, fast=False, inside=None, day_index=0, power=0.0):
        self.line += 1
        out_c = _outside_c(ts)
        tpms_base = 2.9 + (out_c - 20) * 0.006
        leak = 0.0
        if self.car.leak_until and ts.date() <= self.car.leak_until:
            leak = 0.35 * (1 - (self.car.leak_until - ts.date()).days / 10)
        fields = {
            "Gear": gear if state != "asleep" else None, "VehicleSpeed": round(speed, 1),
            "Odometer": round(self.car.odometer, 2), "BatteryLevel": round(self.car.battery, 1),
            "RatedRange": round(self.car.battery / 100 * _range_at_100(day_index), 1),
            "EnergyRemaining": round(self.car.battery / 100 * PACK_KWH * (1 - 0.00005 * day_index), 2),
            "DetailedChargeState": charging, "OutsideTemp": out_c,
            "InsideTemp": inside if inside is not None else round(out_c + (6 if state == "asleep" else 2), 1),
            "Locked": state != "online" or self.rng.random() > 0.02, "DrivePower": round(power, 1),
            "TpmsPressureFl": round(tpms_base - leak + self.rng.uniform(-0.02, 0.02), 2),
            "TpmsPressureFr": round(tpms_base + self.rng.uniform(-0.02, 0.02), 2),
            "TpmsPressureRl": round(tpms_base + 0.05 + self.rng.uniform(-0.02, 0.02), 2),
            "TpmsPressureRr": round(tpms_base + 0.05 + self.rng.uniform(-0.02, 0.02), 2),
            "Version": self.car.version, "FastChargerPresent": fast,
        }
        if loc is not None:
            fields["Location"] = {"latitude": round(loc[0], 6), "longitude": round(loc[1], 6)}
        if charger_power is not None:
            fields["ACChargingPower" if not fast else "DCChargingPower"] = charger_power
        if energy_added is not None:
            fields["ChargeEnergyAdded"] = round(energy_added, 2)
        fields = {k: v for k, v in fields.items() if v is not None}
        connected = None if state == "online" else False
        if state in ("online", "driving", "charging"):
            connected = True
        self.rows.append(ImportedRow(self.line, ts, fields, connected))

    def _drive(self, ts: datetime, a, b, day_index: int, highway: bool = False) -> datetime:
        miles = _haversine_miles(a, b) * (1.28 if not highway else 1.12)
        cruise = self.rng.uniform(62, 74) if highway else self.rng.uniform(28, 42)
        minutes = max(6.0, miles / cruise * 60 + self.rng.uniform(1, 5))
        steps = max(4, int(minutes * 60 / STEP.total_seconds()))
        # A curved path: offset the midpoint perpendicular to the straight line.
        bend = self.rng.uniform(-0.18, 0.18)
        mid = ((a[0] + b[0]) / 2 + bend * (b[1] - a[1]), (a[1] + b[1]) / 2 - bend * (b[0] - a[0]))
        temp_factor = 1 + max(0, 18 - _outside_c(ts)) * 0.012 + max(0, _outside_c(ts) - 30) * 0.006
        wh = WH_PER_MILE * temp_factor * (1.08 if highway else 1.0)
        start_odo = self.car.odometer
        self._row(ts, "driving", a, 0, "D", day_index=day_index, inside=21.5)
        for i in range(1, steps + 1):
            t = i / steps
            p = ((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * mid[0] + t * t * b[0],
                 (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * mid[1] + t * t * b[1])
            ramp = min(1.0, i / 3, (steps - i + 1) / 3)
            wave = 1 + 0.18 * math.sin(i / (2.5 if not highway else 7)) + self.rng.uniform(-0.08, 0.08)
            speed = max(0.0, cruise * ramp * wave)
            if not highway and self.rng.random() < 0.06:
                speed = 0.0  # traffic light
            self.car.odometer = start_odo + miles * t
            self.car.battery -= (miles / steps) * wh / 1000 / PACK_KWH * 100
            power = speed * wh / 1000 * 1.9 + self.rng.uniform(-3, 6) if speed > 0 else 0.4
            self._row(ts + STEP * i, "driving", p, speed, "D", day_index=day_index, inside=21.5, power=power)
        end = ts + STEP * (steps + 1)
        self._row(end, "online", b, 0, "P", day_index=day_index, inside=21.5)
        return end

    def _charge(self, ts: datetime, loc, target: float, fast: bool, day_index: int) -> datetime:
        added = 0.0
        self._row(ts, "online", loc, charging="Starting", fast=fast, day_index=day_index)
        t = ts + timedelta(minutes=1)
        while self.car.battery < target:
            if fast:
                kw = 150 if self.car.battery < 45 else max(35.0, 150 - (self.car.battery - 45) * 2.9)
                step = timedelta(minutes=1)
            else:
                kw = 7.6 if self.car.battery < 92 else 4.0
                step = timedelta(minutes=10)
            kwh = kw * step.total_seconds() / 3600
            added += kwh
            self.car.battery = min(target, self.car.battery + kwh * 0.92 / PACK_KWH * 100)
            self._row(t, "charging", loc, charging="Charging", charger_power=round(kw + self.rng.uniform(-1, 1), 1),
                      energy_added=added, fast=fast, day_index=day_index)
            t += step
        self._row(t, "online", loc, charging="Complete", energy_added=added, fast=fast, day_index=day_index)
        return t + timedelta(minutes=2)

    def _park(self, ts: datetime, until: datetime, loc, day_index: int) -> None:
        t = ts + timedelta(minutes=15)
        if until - ts > timedelta(minutes=45):
            self._row(t, "online", loc, day_index=day_index)
            t += timedelta(minutes=20)
            while t < until - timedelta(minutes=5):
                self.car.battery -= 0.018
                self._row(t, "asleep", None, day_index=day_index)
                t += timedelta(minutes=45)
        self._row(until - timedelta(minutes=4), "online", loc, day_index=day_index)

    def run(self) -> list[ImportedRow]:
        for di in range(self.days):
            day = self.start + timedelta(days=di)
            if di and di % 41 == 0:
                major, minor, patch = self.car.version.split(".")
                self.car.version = f"{major}.{int(minor) + 6}.{self.rng.randint(1, 9)}"
            if self.rng.random() < 0.012:
                self.car.leak_until = day + timedelta(days=9)
            base = datetime(day.year, day.month, day.day, tzinfo=TZ)
            weekday = day.weekday() < 5
            here = HOME
            t = base + timedelta(hours=7, minutes=self.rng.randint(15, 55))
            self._row(base + timedelta(hours=1), "asleep", None, day_index=di)
            if weekday:
                t = self._drive(t, HOME, DESTINATIONS["Office"], di)
                leave = base + timedelta(hours=17, minutes=self.rng.randint(0, 50))
                self._park(t, leave, DESTINATIONS["Office"], di)
                t = self._drive(leave, DESTINATIONS["Office"], HOME, di)
                if self.rng.random() < 0.35:
                    t = self._drive(t + timedelta(minutes=40), HOME, DESTINATIONS["Climbing gym"], di)
                    back = t + timedelta(minutes=self.rng.randint(70, 110))
                    self._park(t, back, DESTINATIONS["Climbing gym"], di)
                    t = self._drive(back, DESTINATIONS["Climbing gym"], HOME, di)
            elif di % 29 == 13:
                t = base + timedelta(hours=8)
                t = self._drive(t, HOME, DESTINATIONS["Round Rock Supercharger"], di, highway=True)
                t = self._drive(t, DESTINATIONS["Round Rock Supercharger"], DESTINATIONS["Waco Supercharger"], di, highway=True)
                t = self._charge(t, DESTINATIONS["Waco Supercharger"], 80, True, di)
                back = t + timedelta(hours=self.rng.randint(3, 5))
                self._park(t, back, DESTINATIONS["Waco Supercharger"], di)
                t = self._drive(back, DESTINATIONS["Waco Supercharger"], DESTINATIONS["Round Rock Supercharger"], di, highway=True)
                if self.car.battery < 35:
                    t = self._charge(t, DESTINATIONS["Round Rock Supercharger"], 70, True, di)
                t = self._drive(t, DESTINATIONS["Round Rock Supercharger"], HOME, di, highway=True)
            else:
                t = base + timedelta(hours=10, minutes=self.rng.randint(0, 90))
                t = self._drive(t, HOME, DESTINATIONS["Grocery"], di)
                back = t + timedelta(minutes=self.rng.randint(25, 60))
                self._park(t, back, DESTINATIONS["Grocery"], di)
                t = self._drive(back, DESTINATIONS["Grocery"], HOME, di)
            evening = base + timedelta(hours=22)
            if t < evening:
                self._park(t, evening, here, di)
                t = evening
            if self.car.battery < 72:
                t = self._charge(t, HOME, 80.0, False, di)
            self._row(t + timedelta(minutes=30), "asleep", None, day_index=di)
        return sorted(self.rows, key=lambda r: r.ts)


def generate(days: int = 180, end: date | None = None, seed: int = 7) -> tuple[list[ImportedRow], list[Place]]:
    end = end or datetime.now(UTC).astimezone(TZ).date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return DemoGenerator(start, days, seed).run(), PLACES
