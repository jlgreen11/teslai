import shutil

from typer.testing import CliRunner

from teslai.cli import app
from teslai.paths import REPO_DIR

runner = CliRunner()


def _init(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copy(REPO_DIR / ".env.example", tmp_path / ".env.example")
    r = runner.invoke(app, ["init", "--domain", "cars.example.org", "--timezone", "UTC"])
    assert r.exit_code == 0, r.output
    env = (tmp_path / ".env").read_text().replace("TESLA_VIN=", "TESLA_VIN=5YJYGDEE1LF000001")
    (tmp_path / ".env").write_text(env)
    for k in list(__import__("os").environ):
        if k.startswith(("TESLA", "TESLAI")):
            monkeypatch.delenv(k, raising=False)


def test_init_creates_token_key(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    key = tmp_path / "secrets" / "token.key"
    assert key.exists() and oct(key.stat().st_mode)[-3:] == "600"


def test_telemetry_push_dry_run_shows_fields_and_cost_without_network(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    from teslai import cli

    monkeypatch.setattr(cli, "http_client", lambda **k: (_ for _ in ()).throw(AssertionError("no network")))
    r = runner.invoke(app, ["telemetry", "push"])
    assert r.exit_code == 0, r.output
    assert "fields to telemetry.cars.example.org:4443" in r.output
    assert "Cost upper bound" in r.output and "Dry run" in r.output


def test_pair_prints_virtual_key_link(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    r = runner.invoke(app, ["pair"])
    assert r.exit_code == 0 and "https://tesla.com/_ak/cars.example.org" in r.output


def test_register_without_client_id_explains_fix(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    r = runner.invoke(app, ["tesla", "register"])
    assert r.exit_code == 1 and "TSL-TESLA-UNCONFIGURED" in r.output
