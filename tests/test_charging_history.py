from datetime import UTC, datetime, timedelta

import httpx
import pytest

from teslai.errors import TeslaiError
from teslai.tesla.charging_history import best_match, fetch_history, parse_record

REC = {"sessionId": 123, "siteLocationName": "Belton, MO", "chargeStartDateTime": "2026-07-01T18:00:00-05:00",
       "chargeStopDateTime": "2026-07-01T18:35:00-05:00",
       "fees": [{"feeType": "CHARGING", "currencyCode": "USD", "totalDue": 11.5},
                {"feeType": "PARKING", "currencyCode": "USD", "totalDue": 1.0}],
       "invoices": [{"fileName": "a.pdf", "contentId": "c-1", "invoiceType": "IMMEDIATE"}]}


def test_parse_record_sums_fees_and_keeps_invoice_ids():
    r = parse_record(REC)
    assert (r.tesla_session_id, r.site_name, r.currency, r.total_due) == ("123", "Belton, MO", "USD", 12.5)
    assert r.start_ts == datetime(2026, 7, 1, 23, tzinfo=UTC) and r.invoice_content_ids == ["c-1"]


def test_free_supercharging_and_mixed_currency():
    free = parse_record({**REC, "fees": [{"currencyCode": "USD", "totalDue": 0}]})
    assert free.total_due == 0.0
    mixed = parse_record({**REC, "fees": [{"currencyCode": "USD", "totalDue": 1}, {"currencyCode": "CAD", "totalDue": 2}]})
    assert mixed.currency == "MIXED" and mixed.total_due is None
    nofees = parse_record({**REC, "fees": []})
    assert nofees.total_due is None


def test_unknown_shape_fails_loudly():
    with pytest.raises(TeslaiError) as exc:
        parse_record({"when": "yesterday"})
    assert exc.value.info.code == "TSL-IMPORT-SCHEMA" and "when" in str(exc.value)
    with pytest.raises(TeslaiError):
        parse_record({**REC, "chargeStartDateTime": "2026-07-01T18:00:00"})


def test_fetch_pages_until_short_page():
    calls = []

    def handler(req):
        page = int(req.url.params["pageNo"])
        calls.append(page)
        items = [{**REC, "sessionId": f"{page}-{i}"} for i in range(2 if page == 1 else 1)]
        return httpx.Response(200, json={"data": items})

    recs = fetch_history(httpx.Client(transport=httpx.MockTransport(handler)), "https://fleet", "t", "VIN",
                         datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC), page_size=2)
    assert calls == [1, 2] and len(recs) == 3


def test_best_match_uses_overlap_with_tolerance():
    r = parse_record(REC)
    charges = [
        {"id": 1, "start_ts": r.start_ts - timedelta(hours=3), "end_ts": r.start_ts - timedelta(hours=2)},
        {"id": 2, "start_ts": r.start_ts + timedelta(minutes=4), "end_ts": r.stop_ts + timedelta(minutes=3)},
        {"id": 3, "start_ts": r.stop_ts + timedelta(minutes=10), "end_ts": r.stop_ts + timedelta(minutes=40)},
    ]
    assert best_match(r, charges) == 2
    assert best_match(r, charges[:1]) is None
