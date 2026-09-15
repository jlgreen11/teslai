# Deploy teslai to a server

This runbook takes a fresh Linux VM to a car streaming into teslai. Commands that start with `teslai` run from the repository directory on the server, inside the Python virtual environment, unless a step says to run them in the app container.

Steps marked **(you)** need your accounts, your phone or your car. Everything else is a command.

## 1. Server **(you)**

1. Create an Oracle Cloud Always Free Ampere VM: Ubuntu 24.04, 2 OCPUs, 12 GB RAM, 100 GB boot volume.
2. In the VCN security list, allow inbound TCP 80, 443 and 4443 from anywhere.
3. On the VM, open the same ports in the host firewall:

```bash
sudo iptables -I INPUT -p tcp -m multiport --dports 80,443,4443 -j ACCEPT
sudo netfilter-persistent save
```

## 2. DNS **(you)**

Create two A records pointing at the VM's public IP:

| Name | Purpose |
|---|---|
| `cars.example.org` | Web app and Tesla public key |
| `telemetry.cars.example.org` | Where the car streams (mTLS) |

Wait until both resolve: `dig +short cars.example.org`.

## 3. Install

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 python3.12-venv git
sudo usermod -aG docker "$USER" && newgrp docker
git clone https://github.com/jlgreen11/teslai.git && cd teslai
python3.12 -m venv .venv && . .venv/bin/activate && pip install -e .
teslai init --domain cars.example.org --timezone America/Chicago
docker compose up -d
teslai doctor
```

`teslai doctor` should pass every check except the Tesla app, which comes next.

## 4. Public key and web app

```bash
docker compose --profile edge up -d caddy
curl -fsS https://cars.example.org/.well-known/appspecific/com.tesla.3p.public-key.pem
```

The curl must print a `-----BEGIN PUBLIC KEY-----` block. Tesla rejects registration if it does not.

## 5. Owner login

```bash
teslai owner create --email you@example.org
```

Scan the printed link with an authenticator app and enter a code to confirm. Then sign in at `https://cars.example.org`.

## 6. Tesla developer app **(you)**

At [developer.tesla.com](https://developer.tesla.com), create an application:

| Field | Value |
|---|---|
| Allowed origin | `https://cars.example.org` |
| Redirect URI | `https://cars.example.org/tesla/callback` |
| Scopes | Vehicle Information, Vehicle Location |

Set a billing limit in the developer console. Then add to `.env`:

```
TESLA_CLIENT_ID=...
TESLA_CLIENT_SECRET=...
TESLA_REGION=na
TESLA_VIN=...
TESLA_REDIRECT_URI=https://cars.example.org/tesla/callback
```

Register and log in:

```bash
teslai tesla register
teslai tesla login
```

`login` prints a Tesla link. Approve access; the browser lands on a "Not found" page at `/tesla/callback`. That is expected. Copy the full URL from the address bar and paste it into the prompt.

## 7. Pair the virtual key **(you, near the car)**

```bash
teslai pair
```

Open the printed `https://tesla.com/_ak/cars.example.org` link on the phone with the Tesla app, near the car, and approve the key.

## 8. Start telemetry

```bash
teslai telemetry server-config
docker compose --profile edge up -d
docker compose exec app teslai telemetry push            # dry run: fields and cost upper bound
docker compose exec app teslai telemetry push --yes
docker compose exec app teslai telemetry status
```

The push runs inside the app container because only it can reach the signing proxy. Wake the car in the Tesla app if `status` reports `TSL-CONFIG-UNSYNCED`.

## 9. Confirm data is arriving

```bash
docker compose logs worker --tail 20
ls -l recordings/
```

Drive or wake the car, then open the day view. If nothing arrives within a few minutes of the car waking, run `teslai doctor` and follow the first failure.

## Alerts

`teslai monitor` sends alerts to every Apprise URL in `TESLAI_NOTIFY_URLS`, for example `pover://user@token` for Pushover. Car alerts are configured in `config/rules.yaml`; copy `config/rules.example.yaml` to start:

| Alert | Default |
|---|---|
| Unlocked while parked away from a place of kind `home` | 10 minutes |
| A window open while parked | 10 minutes |
| Tire pressure outside limits | below 2.6 or above 3.5 bar |
| New software version | once per version |
| Drive and charge summaries | drives of 1+ mile and charges of 1+ kWh from live telemetry |

Each alert fires once and sends a "Resolved" notice when it clears. Load your places first (`teslai places load config/places.csv`) so being at home does not trigger the unlocked alert.

## Backups

The `backup` service dumps the database nightly into `backups/`, keeps 14 days, and restores the newest dump into a scratch database every 7 dumps to check it. The monitor alerts if the newest dump is older than 36 hours or the restore check fails.

```bash
docker compose run --rm backup once      # dump now
docker compose run --rm backup verify    # restore check now
cat backups/last-verify.json
```

**Offsite copies are not automated yet.** Until they are, copy `backups/` off the VM, for example from the Mac Mini: `rsync -a vm:teslai/backups/ ~/teslai-backups/`.

## Before cutting over from TeslaFi

Do not remove TeslaFi's telemetry config until the history gate passes and the rollback runbook has been rehearsed. See docs/ARCHITECTURE.md, section 7.
