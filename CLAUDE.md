# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

teslai is a self-hosted (or free-to-host) replacement for TeslaFi.com: logging drives, charges, idle and sleep; reports; alerts; vehicle control and automation; and a migration of years of the owner's TeslaFi history.

## Status

**Architecture review phase. Do not write application code yet.** The proposal is `docs/ARCHITECTURE.md`, and its "Decisions needed before building" section must be answered by the owner first. There are no build, lint, or test commands yet. Update this file when the stack is confirmed.

## Load-bearing design constraints

- Ingest via Tesla **Fleet Telemetry** (car pushes over mTLS) and use the **Fleet API** only for setup, commands and rare reads. Do not build on the unofficial Owner API.
- Commands, schedules and triggers are deferred: the owner's TeslaFi account has controls disabled and zero commands used. v1 is logging, alerts, summaries, charging cost (TOU, free locations, Supercharger credits) and battery trend.
- Never wake the car to log. Fleet API usage is billed per signal, command, and wake; stay inside Tesla's $10/month credit.
- TeslaFi imports and live telemetry both land in `raw_states` and go through the **same session builder**, so historical and new drives/charges are computed identically. Migration is accepted only when derived sessions reconcile with TeslaFi's own drive and charge exports.
- Telemetry needs end-to-end mTLS on a public hostname. TLS-terminating tunnels (e.g. Cloudflare Tunnel) cannot sit in front of it.

## Repository notes

- The GitHub repo `jlgreen11/teslai` is **public**. Tesla tokens, signing keys, TeslaFi credentials, and TeslaFi CSV exports must never be committed.
- Scraped TeslaFi places, tariffs, exports and tokens contain personal data and must stay in git-ignored paths.
