"""Load TeslaFi's own drive and charge history as the history gate's answer key.

Two formats are accepted:

1. Normalized monthly totals, for hand-made or pre-processed keys:
       {"2026-07": {"drive_count": 41, "miles": 812.4, "charge_count": 19, "kwh_added": 240.1}}

2. Raw JSON from TeslaFi's history API (history.php?command=drives / charges),
   either a list of records or {"response": [...]}. TeslaFi's field names are not
   documented, so the loader looks for known candidates and fails loudly with
   TSL-IMPORT-SCHEMA, listing the keys it saw, when none match. Add the real
   names to the candidate lists after inspecting a real export.
"""

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from teslai.errors import TeslaiError

DATE_KEYS = ["startDate", "start_date", "StartDate", "Date", "date", "Start Date"]
DISTANCE_KEYS = ["distance", "Distance", "miles", "Miles", "odometerDiff", "Distance (mi)"]
ENERGY_KEYS = ["charge_energy_added", "energyAdded", "kWh", "kwh", "kwh_added", "Energy Added"]
DATE_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M",
                "%Y-%m-%dT%H:%M:%S"]


def _records(raw) -> list[dict]:
    if isinstance(raw, dict) and isinstance(raw.get("response"), list):
        return raw["response"]
    if isinstance(raw, list):
        return raw
    raise TeslaiError("TSL-IMPORT-SCHEMA", "answer key JSON is neither a list nor {response: [...]}")


def _pick(record: dict, keys: list[str], what: str, source: Path):
    for k in keys:
        if k in record and record[k] not in (None, ""):
            return record[k]
    raise TeslaiError("TSL-IMPORT-SCHEMA",
                      f"{source.name}: no {what} field; saw keys {sorted(record)[:20]}")


def _parse_local(value: str, tz: ZoneInfo) -> datetime:
    for fmt in DATE_FORMATS:
        try:
            naive = datetime.strptime(str(value).strip(), fmt)  # noqa: DTZ007
        except ValueError:
            continue
        return naive.replace(tzinfo=tz).astimezone(UTC)
    raise TeslaiError("TSL-IMPORT-SCHEMA", f"unrecognized date format {value!r}")


def _is_normalized(raw) -> bool:
    return isinstance(raw, dict) and raw and all(
        isinstance(k, str) and len(k) == 7 and k[4] == "-" and isinstance(v, dict)
        for k, v in raw.items())


def load_answer_key(paths: list[Path], tz: ZoneInfo) -> dict[str, dict[str, float]]:
    months: dict[str, dict[str, float]] = defaultdict(
        lambda: {"drive_count": 0, "miles": 0.0, "charge_count": 0, "kwh_added": 0.0})
    for path in paths:
        raw = json.loads(path.read_text())
        if _is_normalized(raw):
            for month, vals in raw.items():
                for k, v in vals.items():
                    months[month][k] = months[month].get(k, 0) + float(v)
            continue
        for rec in _records(raw):
            ts = _parse_local(_pick(rec, DATE_KEYS, "start date", path), tz)
            month = f"{ts.astimezone(tz):%Y-%m}"
            if any(k in rec for k in DISTANCE_KEYS):
                months[month]["drive_count"] += 1
                months[month]["miles"] += float(_pick(rec, DISTANCE_KEYS, "distance", path))
            elif any(k in rec for k in ENERGY_KEYS):
                months[month]["charge_count"] += 1
                months[month]["kwh_added"] += float(_pick(rec, ENERGY_KEYS, "energy", path))
            else:
                raise TeslaiError("TSL-IMPORT-SCHEMA",
                                  f"{path.name}: record has neither distance nor energy; "
                                  f"saw keys {sorted(rec)[:20]}")
    return dict(months)
