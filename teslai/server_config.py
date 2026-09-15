"""Generate fleet-telemetry's server config and the signing proxy's TLS certificate.

fleet-telemetry (tesla/fleet-telemetry) terminates the car's mTLS connection with
the private-CA server certificate and publishes every record type to Mosquitto:

    records:  V, connectivity, alerts, errors  ->  mqtt
    reliable_ack on, with V acked only after the MQTT publish succeeds

The vehicle-command proxy (tesla/vehicle-command) signs config pushes. It serves
HTTPS on the internal compose network only, with a certificate issued by the same
private CA, so teslai verifies it with TESLA_PROXY_CA=<secrets>/ca.cert.pem.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from teslai.secrets import SERVER_DAYS, SecretPaths


def fleet_telemetry_config(port: int = 4443, mqtt_broker: str = "mosquitto:1883",
                           topic_base: str = "telemetry",
                           cert_dir: str = "/etc/teslai-certs") -> dict:
    return {
        "host": "0.0.0.0",
        "port": port,
        "log_level": "info",
        "json_log_enable": True,
        "namespace": "teslai",
        "reliable_ack": True,
        "reliable_ack_sources": {"V": "mqtt", "connectivity": "mqtt"},
        "rate_limit": {"enabled": True, "message_interval_time": 30, "message_limit": 1000},
        "records": {"V": ["mqtt"], "connectivity": ["mqtt"], "alerts": ["mqtt"],
                    "errors": ["mqtt"]},
        "mqtt": {
            "broker": mqtt_broker,
            "client_id": "teslai-fleet-telemetry",
            "topic_base": topic_base,
            "qos": 1,
            "retained": False,
            "connect_timeout_ms": 30000,
            "publish_timeout_ms": 2500,
            "disconnect_timeout_ms": 250,
            "connect_retry_interval_ms": 10000,
            "keep_alive_seconds": 30,
        },
        "tls": {"server_cert": f"{cert_dir}/telemetry-server.cert.pem",
                "server_key": f"{cert_dir}/telemetry-server.key.pem"},
    }


def proxy_cert_paths(paths: SecretPaths) -> tuple[Path, Path]:
    return paths.root / "proxy-tls.cert.pem", paths.root / "proxy-tls.key.pem"


def ensure_proxy_cert(paths: SecretPaths, host: str = "vehicle-command",
                      now: datetime | None = None) -> tuple[Path, Path]:
    cert_path, key_path = proxy_cert_paths(paths)
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path
    now = now or datetime.now(UTC)
    ca_key = serialization.load_pem_private_key(paths.ca_key.read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(paths.ca_cert.read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=SERVER_DAYS))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host), x509.DNSName("localhost")]),
                       critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    key_path.chmod(0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def write_fleet_telemetry_config(path: Path, **kwargs) -> Path:
    path.write_text(json.dumps(fleet_telemetry_config(**kwargs), indent=2) + "\n")
    return path
