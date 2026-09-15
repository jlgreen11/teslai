# TODOS

Deferred work from the /autoplan review on 2026-09-14. See docs/ARCHITECTURE.md.

## Analytics differentiators
- **What:** Battery degradation modeled with confidence intervals, a time-of-use charging optimizer, and anomaly detection on parked drain.
- **Why:** These are the features that would make teslai better than TeslaFi, not just a copy of it.
- **Pros:** Uses the owner's quantitative strengths; no competitor does these well.
- **Cons:** New scope beyond parity.
- **Context:** Needs phases 1–3 data first. Start with the degradation model on imported history.
- **Effort:** M (human) / S (CC). **Priority:** P2. **Depends on:** phase 3.

## Standalone TeslaFi export-and-validate tool
- **What:** A small open-source tool that downloads a TeslaFi history and reconciles it against any logger's sessions.
- **Why:** Every TeslaFi user leaving the service faces the same migration risk.
- **Pros:** Useful to others with little extra work, since the importer and gate exist.
- **Cons:** Support burden.
- **Context:** Extract from phase 1's importer and history gate.
- **Effort:** M / S. **Priority:** P3. **Depends on:** phase 1.

## Sharing gate work
- **What:** Product name without "Tesla", LLC, RLS policies, signup and invites, legal pages, paid hosting, public Tesla app registration.
- **Why:** Only needed if others use teslai.
- **Pros:** Opens a hosted or self-host product.
- **Cons:** Large effort; demand and margin unproven against $4–8/month competitors.
- **Context:** Gate criteria in docs/ARCHITECTURE.md section 8.
- **Effort:** L / M. **Priority:** P3. **Depends on:** 60+ days solo use, measured cost, 20 committed beta users.

## Community features
- **What:** Software tracker, leaderboards, fleet statistics, fleet battery-degradation average.
- **Why:** TeslaFi parity.
- **Pros:** Parity.
- **Cons:** Meaningless without hundreds of cars.
- **Context:** Only after the sharing gate passes.
- **Effort:** M / S. **Priority:** P3. **Depends on:** sharing gate.

## Alexa skill
- **What:** Voice queries for battery and range.
- **Why:** TeslaFi parity.
- **Pros:** Parity.
- **Cons:** Low value; skill certification overhead.
- **Context:** TeslaFi offers it; the owner's usage is unknown.
- **Effort:** S / S. **Priority:** P3. **Depends on:** phase 4.

## Self-hoster onboarding friction
- **What:** Offer a shared registered Tesla app or optional hosted Fleet API proxy so self-hosters skip their own developer registration, domain and CA.
- **Why:** Competing self-hosted tools reportedly let users pair against an already-registered app, often under an hour; teslai needs a per-user Tesla registration.
- **Pros:** Makes a self-host kit realistic for TeslaFi refugees.
- **Cons:** Requires an LLC and a public Tesla app; shared-app operation is a hosted-service burden.
- **Context:** Only relevant if the sharing gate passes. Verify competitors' current onboarding first; this claim was not re-checked in review.
- **Effort:** M / S. **Priority:** P3. **Depends on:** sharing gate.
