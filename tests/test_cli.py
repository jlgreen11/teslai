import shutil
from pathlib import Path

from typer.testing import CliRunner

from teslai.cli import app
from teslai.doctor import run_checks
from teslai.paths import REPO_DIR
from teslai.secrets import SecretPaths, cert_days_left, server_cert_signed_by_ca

runner = CliRunner()


def _init(tmp_path: Path, *extra: str):
    shutil.copy(REPO_DIR / ".env.example", tmp_path / ".env.example")
    return runner.invoke(
        app,
        ["init", "--domain", "cars.example.org", "--timezone", "America/Chicago",
         "--env-file", str(tmp_path / ".env"), "--secrets-dir", str(tmp_path / "secrets"),
         *extra],
    )


def test_init_generates_env_and_valid_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _init(tmp_path)
    assert result.exit_code == 0, result.output
    env = (tmp_path / ".env").read_text()
    assert "TESLAI_DOMAIN=cars.example.org" in env
    assert "TESLAI_TELEMETRY_HOST=telemetry.cars.example.org" in env
    assert "CHANGE_ME" not in env
    assert oct((tmp_path / ".env").stat().st_mode)[-3:] == "600"
    paths = SecretPaths(tmp_path / "secrets")
    assert all(p.exists() for p in paths.all())
    assert server_cert_signed_by_ca(paths)
    assert cert_days_left(paths.server_cert) > 1000
    assert oct(paths.ca_key.stat().st_mode)[-3:] == "600"


def test_init_refuses_to_overwrite_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _init(tmp_path).exit_code == 0
    second = _init(tmp_path)
    assert second.exit_code == 1
    assert "Refusing to overwrite" in second.output
    assert _init(tmp_path, "--force").exit_code == 0


def test_init_rejects_invalid_timezone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copy(REPO_DIR / ".env.example", tmp_path / ".env.example")
    r = runner.invoke(app, ["init", "--domain", "x.org", "--timezone", "Mars/Olympus",
                            "--env-file", str(tmp_path / ".env"),
                            "--secrets-dir", str(tmp_path / "secrets")])
    assert r.exit_code == 2


def test_rotate_server_cert_keeps_ca(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _init(tmp_path).exit_code == 0
    paths = SecretPaths(tmp_path / "secrets")
    ca_before = paths.ca_cert.read_bytes()
    cert_before = paths.server_cert.read_bytes()
    assert _init(tmp_path, "--rotate-server-cert").exit_code == 0
    assert paths.ca_cert.read_bytes() == ca_before
    assert paths.server_cert.read_bytes() != cert_before
    assert server_cert_signed_by_ca(paths)


def test_doctor_reports_missing_env_with_fix(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["doctor", "--env-file", str(tmp_path / ".env"), "--offline"])
    assert r.exit_code == 1
    assert "TSL-ENV-MISSING" in r.output and "teslai init" in r.output


def test_doctor_offline_passes_after_init_and_skips_tesla(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _init(tmp_path).exit_code == 0
    results = run_checks(tmp_path / ".env", network=False)
    assert all(r.ok or r.skipped for r in results), results
    assert results[-1].code == "TSL-TESLA-UNCONFIGURED" and results[-1].skipped


def test_doctor_detects_ca_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _init(tmp_path).exit_code == 0
    other = tmp_path / "other"
    other.mkdir()
    from teslai.secrets import generate_ca
    generate_ca(SecretPaths(other))
    paths = SecretPaths(tmp_path / "secrets")
    paths.ca_cert.write_bytes((other / "ca.cert.pem").read_bytes())
    results = run_checks(tmp_path / ".env", network=False)
    assert results[-1].code == "TSL-CA-MISMATCH"


def test_doctor_detects_placeholder_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copy(REPO_DIR / ".env.example", tmp_path / ".env")
    results = run_checks(tmp_path / ".env", network=False)
    assert results[-1].code == "TSL-ENV-INCOMPLETE"
    assert "TESLAI_DOMAIN" in results[-1].detail
