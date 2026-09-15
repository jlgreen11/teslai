import json
import shutil

from cryptography import x509
from typer.testing import CliRunner

from teslai.cli import app
from teslai.paths import REPO_DIR
from teslai.secrets import SecretPaths
from teslai.server_config import ensure_proxy_cert, fleet_telemetry_config

runner = CliRunner()


def test_fleet_telemetry_config_routes_all_records_to_mqtt_with_reliable_ack():
    c = fleet_telemetry_config(port=4443)
    assert set(c["records"]) == {"V", "connectivity", "alerts", "errors"}
    assert all(v == ["mqtt"] for v in c["records"].values())
    assert c["reliable_ack"] is True and c["reliable_ack_sources"] == {"V": "mqtt"}
    assert c["mqtt"]["qos"] == 1 and c["mqtt"]["broker"] == "mosquitto:1883"
    assert c["tls"]["server_cert"].endswith("telemetry-server.cert.pem")


def test_server_config_command_writes_config_and_proxy_cert(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copy(REPO_DIR / ".env.example", tmp_path / ".env.example")
    assert runner.invoke(app, ["init", "--domain", "cars.example.org"]).exit_code == 0
    r = runner.invoke(app, ["telemetry", "server-config"])
    assert r.exit_code == 0, r.output
    cfg = json.loads((tmp_path / "secrets" / "fleet-telemetry.json").read_text())
    assert cfg["port"] == 4443
    paths = SecretPaths(tmp_path / "secrets")
    cert = x509.load_pem_x509_certificate((tmp_path / "secrets" / "proxy-tls.cert.pem").read_bytes())
    cert.verify_directly_issued_by(x509.load_pem_x509_certificate(paths.ca_cert.read_bytes()))
    before = (tmp_path / "secrets" / "proxy-tls.cert.pem").read_bytes()
    ensure_proxy_cert(paths)
    assert (tmp_path / "secrets" / "proxy-tls.cert.pem").read_bytes() == before
