"""Loading of the telemetry field specs and the enum mapping table."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from teslai.paths import CONFIG_DIR

FieldKind = Literal["state", "continuous"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: FieldKind
    interval_seconds: int
    minimum_delta: float | None = None
    stale_after_seconds: int | None = None


def load_field_specs(path: Path | None = None) -> dict[str, FieldSpec]:
    raw = yaml.safe_load((path or CONFIG_DIR / "telemetry.yaml").read_text())
    specs: dict[str, FieldSpec] = {}
    for name, cfg in raw["fields"].items():
        kind = cfg.get("kind")
        if kind not in ("state", "continuous"):
            raise ValueError(f"Field {name}: kind must be 'state' or 'continuous', got {kind!r}")
        if kind == "state" and cfg.get("stale_after_seconds") is not None:
            raise ValueError(f"Field {name}: state fields must not have stale_after_seconds")
        specs[name] = FieldSpec(
            name=name,
            kind=kind,
            interval_seconds=int(cfg["interval_seconds"]),
            minimum_delta=cfg.get("minimum_delta"),
            stale_after_seconds=cfg.get("stale_after_seconds"),
        )
    return specs


@dataclass(frozen=True)
class EnumTable:
    version: int
    mappings: dict[str, dict[str, dict[str, str]]]

    def meaning(self, field: str, value: object, source: str = "telemetry") -> str:
        """Map a raw enum value to its builder meaning; unknown values map to 'unknown'."""
        if value is None or value == "":
            return "unknown"
        table = self.mappings.get(field, {}).get(source, {})
        return table.get(str(value), "unknown")


def load_enum_table(path: Path | None = None, overrides: Path | None = None) -> EnumTable:
    raw = yaml.safe_load((path or CONFIG_DIR / "enums.yaml").read_text())
    mappings = {f: dict(v) for f, v in raw["fields"].items()}
    if overrides is not None and overrides.exists():
        extra = yaml.safe_load(overrides.read_text()) or {}
        for field, sources in (extra.get("fields") or {}).items():
            for source, values in sources.items():
                mappings.setdefault(field, {}).setdefault(source, {}).update(values)
    return EnumTable(version=int(raw["version"]), mappings=mappings)


@lru_cache
def default_field_specs() -> dict[str, FieldSpec]:
    return load_field_specs()


@lru_cache
def default_enum_table() -> EnumTable:
    return load_enum_table()
