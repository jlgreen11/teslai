# teslai

A personal Tesla data logger and TeslaFi replacement, built on Tesla's official Fleet Telemetry. It logs drives, charges, idle and sleep time from your own car into your own database, and imports your TeslaFi history.

**Status:** phases 0 to 3 are built and tested, and the TeslaFi-style web app is built; phase 4 is in progress. Running it against a real car needs a server, a domain and a Tesla developer app: follow [docs/runbooks/deploy.md](docs/runbooks/deploy.md). Build details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

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

## Import TeslaFi history (phase 1)

Download your raw logging history from TeslaFi (Settings, Advanced, Download TeslaFi Data) into a folder outside this repository. Then do a dry run:

```bash
teslai import teslafi ~/teslafi-export --tz America/Chicago
```

It prints what it read and skipped per file, then drive and charge totals per month. Nothing is stored until you add `--write --vin <VIN>`.

To check the result against TeslaFi's own numbers, save TeslaFi's drives and charges JSON and run the history gate:

```bash
teslai gate history ~/teslafi-export --tz America/Chicago \
  --answer-key drives.json --answer-key charges.json \
  --switch-date 2024-01-01 --report gate.json
```

Each month passes when drive count, miles, charge count and kWh added are within 1% of TeslaFi and drive miles agree with the odometer. The command exits non-zero if any month fails.

## Web app

The web app shows what TeslaFi shows, in a dark, fast interface:

- **Status bar:** state, battery, range, odometer and software, and a top-down car with tire pressures, temperatures and the lock.
- **Today:** the battery curve shaded by drives, charges and sleep, a session timeline, and daily totals.
- **Drives, Charges and Parked:** filterable lists with totals, charts and charging locations.
- **Drive and charge detail:** the route map plus speed, battery, power, temperature and charger-power charts, with previous and next.
- **Calendar and analytics:** month and year calendars, battery health, efficiency by temperature and speed, tire pressure, and a lifetime map.

To try it without a car, generate six months of synthetic history for a fictional demo car:

```bash
docker compose up -d
teslai demo seed --days 180
```

Then sign in at http://localhost:8000. The Docker image builds the web app automatically. To work on the frontend with hot reload, run the API on port 8000 and start Vite, which proxies `/api` to it:

```bash
cd web && npm ci && npm run dev
```

## Development

```bash
ruff check .
pytest -q -m "not integration"
TESLAI_TEST_DATABASE_URL=postgresql+psycopg://teslai:<password>@localhost:5432/postgres \
  TESLAI_TEST_MQTT_HOST=localhost pytest -q -m integration
cd web && npm run lint && npm run build
```

Test fixtures in this repository are synthetic. Never commit TeslaFi exports, recorded telemetry, `.env` files or anything under `secrets/`.

## License

MIT
