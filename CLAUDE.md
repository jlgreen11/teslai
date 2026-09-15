# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

teslai replaces TeslaFi.com for the owner's own Tesla: logging, analytics, alerts and, later, controls, plus import of 46 months of TeslaFi history. **Scope is personal tool first.** Sharing with other owners (hosted or self-host kit) is a separate decision behind the sharing gate in `docs/ARCHITECTURE.md` section 8. Do not build signup, invites, RLS policies, community features or legal pages before that gate passes.

## Status and commands

Phases 0 to 3 are built (ingest, TeslaFi import, sessions, alerts, owner login), plus a TeslaFi-style React web app. Phase 4 (controls, share links) is not built. Build status lives in `docs/ARCHITECTURE.md`.

- Python: `ruff check .`, `pytest -q -m "not integration"`; integration tests need `TESLAI_TEST_DATABASE_URL` and `TESLAI_TEST_MQTT_HOST` pointing at the compose Postgres and Mosquitto.
- Web (`web/`, React + Vite + TypeScript + Tailwind + ECharts + MapLibre): `npm run lint`, `npm run build`. The build writes to `teslai/api/web` (git-ignored), which FastAPI serves for every non-API path.
- Demo data: `teslai demo seed --days 180` writes synthetic samples and sessions for a fictional car.
- Web endpoints live in `teslai/api/views.py`; derived views (calendar, efficiency, locations, tracks) are pure functions in `teslai/insights.py`; time series live in the `samples` table (`teslai/samples.py`).
- Charts follow the dataviz rules: one y-axis per chart, 2px lines, bars at most 24px, legends for two or more series.

## Load-bearing design constraints

- Ingest via Tesla **Fleet Telemetry** (car pushes over mTLS to one shared server that routes by VIN). Use the **Fleet API** for setup, commands, and Supercharger history. Never build on the unofficial Owner API.
- **Tenancy-ready, single account.** Every table carries `account_id`, and every query goes through one repository layer that filters by it. RLS policies wait for the sharing gate.
- **Telemetry is change-only.** State fields (Gear, Locked, DetailedChargeState, ...) carry forward without an age limit; continuous fields expire after a short per-field limit. Sleep is inferred from connectivity events, never from silence. Enum meanings live in a versioned mapping table, not in scattered branches.
- **Sessions are built on vehicle time** with watermark re-derivation for late events; alerts de-duplicate through `rule_firings`.
- The telemetry server uses a **private CA** pinned in the car's telemetry config; exactly one process refreshes Tesla tokens (single-use, rotating).
- **Never wake the car to log.** Tesla bills per signal, command, wake, and data request, and the hosted service pays for every user's car. Per-vehicle usage is metered in `api_usage` from day one.
- TeslaFi imports and live telemetry both reach `raw_states` and the **same session builder**. Cutover needs two gates: the history gate (within 1% of TeslaFi per month, split at TeslaFi's polling-to-streaming switch) and a 2–4 week live gate against odometer and energy deltas. Record raw MQTT payloads from day one for replay tests.
- Telemetry needs end-to-end mTLS on a public hostname. TLS-terminating tunnels (e.g. Cloudflare Tunnel) cannot sit in front of it.
- Test fixtures in this public repo must be synthetic. Real TeslaFi exports, recorded payloads and scraped places stay in git-ignored paths.

## Repository notes

- The GitHub repo `jlgreen11/teslai` is **public**. Tesla tokens, signing keys, TeslaFi credentials, TeslaFi exports, and scraped places or tariffs contain secrets or personal data and must stay in git-ignored paths.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
