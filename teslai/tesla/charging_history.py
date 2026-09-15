"""Tesla charging history: Supercharger sessions, fees and invoices.

    GET <fleet base>/api/1/dx/charging/history
        ?vin=&startTime=&endTime=&pageNo=&pageSize=&sortBy=&sortOrder=
    GET <fleet base>/api/1/dx/charging/invoice/<contentId>   (invoice PDF)

Only some response field names are confirmed (siteLocationName,
chargeStartDateTime, invoices[].contentId, fees[].currencyCode). The parser
tries known candidates for the rest and raises TSL-IMPORT-SCHEMA, listing the
keys it saw, when a record has no session id or start time.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from teslai.errors import TeslaiError
from teslai.tesla.auth import raise_for_tesla

ID_KEYS = ["sessionId", "chargeSessionId", "id"]
START_KEYS = ["chargeStartDateTime", "chargeStartTime", "startDateTime"]
STOP_KEYS = ["chargeStopDateTime", "unlatchDateTime", "chargeEndDateTime"]
AMOUNT_KEYS = ["totalDue", "netDue", "amountDue"]
MATCH_TOLERANCE = timedelta(minutes=15)


@dataclass
class HistoryRecord:
    tesla_session_id: str
    site_name: str | None
    start_ts: datetime
    stop_ts: datetime | None
    currency: str | None
    total_due: float | None
    invoice_content_ids: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def _first(record: dict, keys: list[str]):
    for k in keys:
        if record.get(k) not in (None, ""):
            return record[k]
    return None


def _ts(value) -> datetime | None:
    if not value:
        return None
    ts = datetime.fromisoformat(str(value))
    if ts.tzinfo is None:
        raise TeslaiError("TSL-IMPORT-SCHEMA", f"charging history time without offset: {value!r}")
    return ts


def parse_record(record: dict) -> HistoryRecord:
    sid, start = _first(record, ID_KEYS), _first(record, START_KEYS)
    if sid is None or start is None:
        raise TeslaiError("TSL-IMPORT-SCHEMA",
                          f"charging history record without id or start; saw keys {sorted(record)[:25]}")
    totals: dict[str, float] = defaultdict(float)
    for fee in record.get("fees") or []:
        amount = _first(fee, AMOUNT_KEYS)
        if amount is not None:
            totals[fee.get("currencyCode") or ""] += float(amount)
    currency, total = (None, None)
    if len(totals) == 1:
        currency, total = next(iter(totals.items()))
        currency = currency or None
    elif len(totals) > 1:
        currency, total = "MIXED", None
    return HistoryRecord(
        tesla_session_id=str(sid), site_name=record.get("siteLocationName"),
        start_ts=_ts(start), stop_ts=_ts(_first(record, STOP_KEYS)), currency=currency,
        total_due=None if total is None else round(total, 2),
        invoice_content_ids=[i["contentId"] for i in record.get("invoices") or [] if i.get("contentId")],
        raw=record)


def fetch_history(http: httpx.Client, base_url: str, token: str, vin: str, start: datetime,
                  end: datetime, page_size: int = 50, max_pages: int = 200) -> list[HistoryRecord]:
    records: list[HistoryRecord] = []
    for page in range(1, max_pages + 1):
        resp = http.get(f"{base_url}/api/1/dx/charging/history", headers={"Authorization": f"Bearer {token}"},
                        params={"vin": vin, "startTime": start.isoformat(), "endTime": end.isoformat(),
                                "pageNo": page, "pageSize": page_size, "sortBy": "chargeStartDateTime",
                                "sortOrder": "ASC"})
        raise_for_tesla(resp, "charging history")
        body = resp.json()
        items = body.get("data") if isinstance(body.get("data"), list) else (body.get("response") or {}).get("data", body.get("response"))
        if not isinstance(items, list):
            raise TeslaiError("TSL-IMPORT-SCHEMA", f"charging history page without a data list; keys {sorted(body)}")
        records.extend(parse_record(r) for r in items)
        if len(items) < page_size:
            break
    return records


def best_match(record: HistoryRecord, charges: list[dict]) -> int | None:
    """The id of the local charge session overlapping this record, allowing 15 minutes of clock skew."""
    r_start = record.start_ts - MATCH_TOLERANCE
    r_end = (record.stop_ts or record.start_ts) + MATCH_TOLERANCE
    best, best_overlap = None, timedelta(0)
    for c in charges:
        c_end = c["end_ts"] or c["start_ts"]
        overlap = min(r_end, c_end) - max(r_start, c["start_ts"])
        if overlap > best_overlap:
            best, best_overlap = c["id"], overlap
    return best
