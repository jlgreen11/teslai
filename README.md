# teslai

A personal Tesla data logger and TeslaFi replacement, built on Tesla's official Fleet Telemetry. It logs drives, charges, idle and sleep time from your own car into your own database, and imports your TeslaFi history.

**Status:** early build. Phase 0 (foundations) is in progress. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and build phases.

## Quickstart (phase 0)

Requirements: Python 3.12 and Docker.

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
teslai init --domain your-domain.example --timezone America/Chicago
```

Expected output:

```
Wrote .env and secrets in secrets.
Public key to host: https://your-domain.example/.well-known/appspecific/com.tesla.3p.public-key.pem
Next: docker compose up -d, then teslai doctor
```

Then check your setup:

```bash
teslai doctor --offline
```

Every failure prints an error code, the likely cause and the exact fix. The full list is in [docs/errors.md](docs/errors.md).

## Development

```bash
pytest -q
ruff check .
```

Test fixtures in this repository are synthetic. Never commit TeslaFi exports, recorded telemetry, `.env` files or anything under `secrets/`.

## License

MIT
