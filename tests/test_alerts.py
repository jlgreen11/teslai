from datetime import UTC, datetime, timedelta

from teslai.alerts import Condition, check_cert, format_alert, month_cost
from teslai.secrets import SecretPaths, generate_ca, generate_server_cert


def test_month_cost_uses_tesla_unit_prices():
    assert month_cost({"signal": 50_000, "command": 100, "wake": 10, "data": 5}) == 5.0 + 0.1 + 0.2 + 0.01


def test_alert_and_resolution_messages_carry_code_and_fix():
    c = Condition("ingest_silence", "1", "TSL-INGEST-SILENT", "no telemetry for 22 min")
    title, body = format_alert(c)
    assert title.startswith("teslai: ") and "TSL-INGEST-SILENT: no telemetry for 22 min" in body
    assert "Fix: " in body
    rtitle, rbody = format_alert(c, resolved=True)
    assert rtitle.startswith("Resolved:") and "cleared" in rbody


def test_cert_check_fires_inside_fourteen_days(tmp_path):
    paths = SecretPaths(tmp_path)
    old = datetime.now(UTC) - timedelta(days=1825 - 10)
    generate_ca(paths, now=old)
    generate_server_cert(paths, "telemetry.example.org", now=old)
    [c] = check_cert(paths.server_cert, datetime.now(UTC))
    assert c.code == "TSL-CERT-EXPIRING"
    assert check_cert(paths.server_cert, old) == []
    assert check_cert(tmp_path / "missing.pem", datetime.now(UTC)) == []
