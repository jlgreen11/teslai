# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

teslai is a product that replicates everything TeslaFi.com offers. The owner uses it first; it then opens to other Tesla owners as a hosted, invite-only service, and the same code is published for self-hosting.

## Status

**Architecture review phase. Do not write application code yet.** The proposal is `docs/ARCHITECTURE.md`. Its "Decisions made" table is settled; section 12 lists what is still open. There are no build, lint, or test commands yet. Update this file when phase 0 lands.

## Load-bearing design constraints

- Ingest via Tesla **Fleet Telemetry** (car pushes over mTLS to one shared server that routes by VIN). Use the **Fleet API** for setup, commands, and Supercharger history. Never build on the unofficial Owner API.
- **Multi-tenant from the first migration.** Every tenant table carries `account_id` and is protected by Postgres row-level security, even while the owner is the only user. One codebase serves both hosted and self-hosted modes.
- **Never wake the car to log.** Tesla bills per signal, command, wake, and data request, and the hosted service pays for every user's car. Per-vehicle usage is metered in `api_usage` from day one.
- TeslaFi imports and live telemetry both land in `raw_states` and go through the **same session builder**. Migration passes only when derived sessions reconcile with TeslaFi's own drive and charge history within 1% per month.
- Telemetry needs end-to-end mTLS on a public hostname. TLS-terminating tunnels (e.g. Cloudflare Tunnel) cannot sit in front of it.
- The public product name must not contain "Tesla" (Tesla trademark guidelines).

## Repository notes

- The GitHub repo `jlgreen11/teslai` is **public**. Tesla tokens, signing keys, TeslaFi credentials, TeslaFi exports, and scraped places or tariffs contain secrets or personal data and must stay in git-ignored paths.
