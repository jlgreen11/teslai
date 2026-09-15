"""Generation of the private CA, telemetry server certificate and app key pair.

The telemetry server uses a private CA whose certificate is pinned in the car's
telemetry config. Public-CA renewals can change the chain and silently break the
car's connection, so the telemetry port never uses Caddy's public certificate.
The app key pair signs vehicle commands and config pushes; its public key is
served at https://<domain>/.well-known/appspecific/com.tesla.3p.public-key.pem.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_DAYS = 3650
SERVER_DAYS = 1825


@dataclass(frozen=True)
class SecretPaths:
    root: Path

    @property
    def ca_key(self) -> Path:
        return self.root / "ca.key.pem"

    @property
    def ca_cert(self) -> Path:
        return self.root / "ca.cert.pem"

    @property
    def server_key(self) -> Path:
        return self.root / "telemetry-server.key.pem"

    @property
    def server_cert(self) -> Path:
        return self.root / "telemetry-server.cert.pem"

    @property
    def app_private_key(self) -> Path:
        return self.root / "tesla-app.private-key.pem"

    @property
    def app_public_key(self) -> Path:
        return self.root / "com.tesla.3p.public-key.pem"

    def all(self) -> list[Path]:
        return [
            self.ca_key,
            self.ca_cert,
            self.server_key,
            self.server_cert,
            self.app_private_key,
            self.app_public_key,
        ]


def _write_private(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.chmod(0o600)


def _key_pem(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def generate_ca(paths: SecretPaths, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "teslai private telemetry CA")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False, data_encipherment=False,
                key_agreement=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    _write_private(paths.ca_key, _key_pem(key))
    paths.ca_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def generate_server_cert(paths: SecretPaths, host: str, now: datetime | None = None) -> None:
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
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_private(paths.server_key, _key_pem(key))
    paths.server_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def generate_app_keys(paths: SecretPaths) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    _write_private(paths.app_private_key, _key_pem(key))
    paths.app_public_key.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )


def cert_days_left(path: Path, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    cert = x509.load_pem_x509_certificate(path.read_bytes())
    return (cert.not_valid_after_utc - now).total_seconds() / 86400


def server_cert_signed_by_ca(paths: SecretPaths) -> bool:
    ca = x509.load_pem_x509_certificate(paths.ca_cert.read_bytes())
    server = x509.load_pem_x509_certificate(paths.server_cert.read_bytes())
    try:
        server.verify_directly_issued_by(ca)
    except (ValueError, TypeError, Exception):  # noqa: BLE001 - any failure means not issued
        return False
    return True
