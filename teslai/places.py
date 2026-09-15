"""Named places and matching sessions to them.

places.csv (gitignored, owner-specific):

    name,kind,latitude,longitude,radius_m
    Home,home,39.0000,-94.5000,60
    Office,other,39.1000,-94.6000,120
    Airport garage,free,39.3000,-94.7100,250

kind decides charging price: home (time-of-use tariff), free, supercharger,
or anything else (public price). A location matches the nearest place whose
radius contains it.
"""

import csv
import math
from dataclasses import dataclass
from pathlib import Path

KINDS = {"home", "work", "free", "supercharger", "other"}
EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class Place:
    name: str
    kind: str
    latitude: float
    longitude: float
    radius_m: float
    id: int | None = None

    def price_kind(self) -> str:
        return {"home": "home", "free": "free", "supercharger": "supercharger"}.get(self.kind, "public")


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def match_place(location: dict | None, places: list[Place]) -> Place | None:
    if not location or location.get("latitude") is None or location.get("longitude") is None:
        return None
    best, best_d = None, float("inf")
    for p in places:
        d = distance_m(location["latitude"], location["longitude"], p.latitude, p.longitude)
        if d <= p.radius_m and d < best_d:
            best, best_d = p, d
    return best


def load_places_csv(path: Path) -> list[Place]:
    places, seen = [], set()
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"name", "kind", "latitude", "longitude", "radius_m"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
        for line, row in enumerate(reader, start=2):
            name = (row["name"] or "").strip()
            kind = (row["kind"] or "").strip().lower()
            if not name:
                raise ValueError(f"{path.name} line {line}: name is empty")
            if name in seen:
                raise ValueError(f"{path.name} line {line}: duplicate name {name!r}")
            if kind not in KINDS:
                raise ValueError(f"{path.name} line {line}: kind must be one of {sorted(KINDS)}")
            try:
                lat, lon, radius = float(row["latitude"]), float(row["longitude"]), float(row["radius_m"])
            except ValueError:
                raise ValueError(f"{path.name} line {line}: latitude, longitude and radius_m must be numbers") from None
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not (5 <= radius <= 5000):
                raise ValueError(f"{path.name} line {line}: coordinates out of range or radius not 5-5000 m")
            seen.add(name)
            places.append(Place(name, kind, lat, lon, radius))
    return places
