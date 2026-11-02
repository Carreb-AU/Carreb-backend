# Backend Work Log — 27 Oct → 2 Nov 2026

Everything shipped in the last week: every fix, improvement, data import and
deployment, with commit hashes, timestamps and approximate time taken
(includes local dev + tests + deploy + live verification).

**Totals:** ~50 commits, 8 production deployments, 2 workbook imports,
~37 hours of work.

---

## Day-by-day summary

| Date | Commits | Theme | ~Time |
|---|---|---|---|
| Thu 27-Oct | 22 | 21-Oct workbook import, image pipeline, Smart Car Match, vehicle lookup, Find a Dealer | ~10 h |
| Fri 28-Oct | 6 | Finance block, spotlight v2, one-variant-per-model filter | ~4.5 h |
| Sat 29-Oct | 4 | GVG in My Garage, Grok estimators, favorite color, dealer radius | ~5 h (+2 h data import) |
| Sun 30-Oct | 4 | Free Match 5 results, AI Smart Match images, Free-tier dial, share card PNG | ~5 h |
| Mon 31-Oct | 8 | Grok fallback search, AI garage add, vehicle data audit mega-fix | ~8 h |
| Tue 1-Nov | 8 | Spec backfill, performance/warming, provenance, Full Insight fix | ~6 h |
| Wed 2-Nov | 5 | Polymorphic vehicle endpoint (GVG/AI cards fix) | ~2.5 h |

---

## Thu 27-Oct — data import + image pipeline + search quality

**21-Oct-26 workbook import (new columns, suppression, verbatim capture)**
`adc3be7` 03:46 · ~2 h
Imported the "02 Vehicles & CORE - 21-Oct-26" workbook on the server; added
the new consolidated-vehicle columns to the DB, row-suppression handling and
verbatim row capture.

**Image pipeline: Grok-vision classifier, orphan cleanup, allowlist scraper**
`338b0ad` 05:14 · ~2.5 h
New curated image scraping with allowlisted sources, a Grok-vision classifier
to reject non-silhouette/undesirable images, and orphan cleanup so old images
are wiped (server disk control). Follow-ups: logger fix `8faa87f` 05:30,
Commons 1200px thumbnails + 429 backoff `5269fec` 06:07, XAI vision model
default grok-4.3 (`grok-2-vision-1212` retired) `9487cc6` 13:03, curated
press-site hero set import with old-image wipe `7a5e8ec` 13:21.

**Smart Car Match: named-car boost, multiple variants, min-5 relaxation**
`e7d6538` 13:43 · `191ae68` 14:06 · `947c6ca` 14:11 · ~2 h
Budget/core-rating filters relaxed, named cars boosted, third-row and luxury
intent extraction, unknown-price cars excluded from budget-constrained
results, cost tie-break. This is the "7-seater SUV returns nothing / always
Audi" fix.

**Vehicle lookup: digit-token matching, coverage scoring**
`4a7d277` 14:25 · `47b7ce0` 14:43 · `21889b2` 14:52 · ~1.5 h
Fixed lookup matching on year coincidences instead of the actual model;
bare-digit model matches now require the brand.

**Free Match: top 5 matches instead of one**
`9533519` 16:34 · ~1 h

**Current vehicle: Grok AI spec lookup for cars missing from the DB**
`f8a27d7` 18:58 · `75ed8ad` 19:05 · ~1.5 h
The manual-entry pipeline: search falls through Carreb DB → GVG → Grok, and
the AI result is stored in its own table (no repeated token spend — the table
doubles as a per-query cache).

**Find a Dealer: migration to New Places API**
`13b52f2` 19:24 · `76eb654` 03:17(next day UTC) · ~2 h
Google's New Places API with spec GET route, fail-loud geocode, and
`locationBias.circle` (locationRestriction turned out to be rectangle-only).

**One variant per model (Smart Match + core search)**
`8ab7918` 28-Oct 03:35 · `0bb5e6a` 05:09 · ~1 h
Same model no longer appears as several trims; cheapest variant wins, then
upgraded to "better-rated trim within +10% of the cheapest price wins".

---

## Fri 28-Oct — finance block + imports

**Finance section in lookup API (FinanceDefaults-driven)**
`40fb0c3` 05:32 · `e3fd931` 05:55 · ~2 h
Full finance block: deposit (10% default), loan amount, term (60), interest
(8.78%, −0.5 pp alt-fuel), balloon, read-only monthly repayment, yearly
interest + fees in the header. Frontend guide expanded with the worked
$41,490 → ~$771/month example.

**Spotlight v2 changeset command + GVG CSV import support**
`73573e7` 18:46 · ~1 h

**Sheet sync: skip annotation rows, widen source text fields**
`750bf55` 19:59 · ~0.5 h

---

## Sat 29-Oct — garage integration + dealer radius

**GVG vehicles can be added to My Garage**
`3f33d2b` 03:33 · ~1 h
`green_vehicle_guide_record_id` accepted end-to-end (garage add + current
vehicle).

**Spec estimators routed through Grok (xAI)**
`34aef22` 04:06 · ~0.5 h
ANCAP rating + engine displacement moved off the dead OpenAI key onto Grok;
30-day cache per car.

**RideReveal favorite color end-to-end**
`c6efdf4` 04:17 · ~1 h
Selected color now captured and returned in the reveal response.

**Find a Dealer 100 km searches**
`8762613` 04:59 · ~1 h
Places bias circle clamped to 50 km max; wider radii work via widening the
query pipeline.

**29-Oct FINAL LAUNCH workbook import (server-side ops, no commit)**
~2 h
Diffed "02 Vehicles & CORE - 29-Oct-26 FINAL LAUNCH" against the previous
sheet, imported all changed tables (vehicles, energy prices, category
defaults, bounds, etc.), reconciled vehicle counts (removed rows not in the
new sheet, verified the unique-vehicle count).

---

## Sun 30-Oct — results completeness + tier rules

**Free Match: real price/spec data for all 5 results**
`118f88e` 03:21 · ~1.5 h
Bug: results 2–5 had `locked: true` and no data (only the first car
rendered). All five now carry full data.

**AI Smart Match: image in every result**
`11bae22` 03:30 · ~0.5 h

**CORE Dial: Free users can view dial matches**
`bb319c4` 15:19 · ~1 h
Free tier moved from "matches button hard-403s" to "results visible; upgrade
prompt only on add-to-garage". Matches endpoint returns vehicles for Free.

**RideReveal share card PNG (headless Chromium)**
`af95490` 19:27 · ~2 h
Share renders the full reveal card as an image instead of a bare link.

---

## Mon 31-Oct — the vehicle data audit

**Grok fallback for current-vehicle search**
`1d397a6` 18:40 · ~1.5 h

**AI vehicle entries accepted in garage add / current vehicle**
`02c982b` 18:56 · `71af6e2` 19:03 · ~1 h

**First garage add becomes current vehicle automatically**
`beffd7c` 19:10 · ~0.5 h

**Auto-route GVG/AI ids mis-sent as vehicle_catalogue_id**
`bcf64c8` 19:22 · ~0.5 h

**Garage AI/GVG cards: full spec + image fallback**
`1cd41b1` 19:39 · `7640268` 19:58 · ~2.5 h
AI/GVG garage rows got the complete card; AI entries get all cost fields
from the Data & Assumptions sheet defaults at creation; silhouettes for
images.

**Complete vehicle data audit (the big one)**
`2118fc3` 23:32 · ~4 h
Canonical `build_vehicle_card` service: every surface (lookup, AI search,
Smart Car Finder, AI Smart Match, garage, current vehicle, public API)
answers with the same complete schema; per-field `field_sources` provenance
(`db`/`default`/`ai`); DB → sheet-defaults → AI fallback hierarchy; garage
add dedupe; **one free RideReveal** entitlement for free tier with
failure-refund; 202 tests green.

---

## Tue 1-Nov — backfill, performance, honesty

**Fill null spec fields on AI/GVG cards**
`b6556a9` 03:43 · ~1 h

**AI estimate warming moved off the request path**
`2ba4dab` 03:54 · `4d7bfc0` 04:01 · `76688fb` 04:18 · ~2 h
Cold Grok calls no longer block user requests; fire-and-forget warmers with
concurrency, 45 s timeouts, and failure caching of 1 h (not 30 days) so
outages self-heal.

**Honest provenance for AI cost fields; integer tow ratings**
`bf26436` 04:41 · ~1 h
AI-entry cost fields are sheet-sourced, not AI-sourced — badges now say so.

**GVG/AI current vehicles expose full engine_data**
`e497076` 05:12 · ~1 h
Running costs, CO₂ p.a., km p.a. — same shape as catalogue cars.

**Full Insight upgrade prompt bug + Carreb spec backfill**
`52e279b` 05:41 · `065996c` 05:46 · ~1.5 h
Archived cars no longer count against the vehicle cap; nightly sweep now
also covers Carreb rows.

**AI spec estimator: longer timeout, failure retry, variant fallback**
`e409540` 16:01 · ~1 h

**fuel_range_km alias**
`d5abb68` 16:18 · ~0.5 h
"Est. fuel range" row fills for combustion cars (walks
wltp → fuel_range → range chain).

**Ops:** purged 239 poisoned 30-day cache keys live on the server (cached
failures from the Grok outage that made ANCAP/engine estimates look
permanently unavailable).

---

## Wed 2-Nov — GVG/AI vehicle cards (the last open bug)

**Polymorphic `/api/vehicles/<id>/`** — `f56030a` 03:47 · ~2.5 h
GVG/AI garage & current-vehicle cards showed no details because the detail
endpoint 404'd for non-catalogue ids. It now resolves Carreb → GVG → AI and
returns a catalogue-shaped payload (all mapper aliases + `engine_data`),
cached 15 min. **No frontend changes needed.**

Supporting fixes, same task:
- `2f60f98` 03:52 — engine_data resale prefers the record's stored estimate
  (killed a 550000 vs 67500 self-inconsistency on the live AI Camry).
- `56196d0` 04:03 — frontend guide: `Frontend API Guide — GVG & AI Vehicle
  Details via Vehicle API (Nov 2026).md`.
- `e103880` 04:08 — garage/current-vehicle detail `name: null` fix.
- `2d77a09` 04:15 — resale derivation moved into the canonical card so every
  surface gets it.

Live-verified: GVG 2015 Corolla garage card → name, $1,850 resale, 902 km
fuel range, image; AI 2015 Camry → name, $5,500 resale (consistent in both
places), 897 km; Carreb endpoint byte-identical.

**Free Plan requirements E2E verification (no code change — audit +
live test with a fresh free account `free_e2e_…@example.com`)** · ~1 h
- **One current vehicle:** set → 200 with full engine_data; second garage
  add → 403 `"Plan limit reached… allows 1 vehicles"` with cap_counter
  `{used: 1, limit: 1}`.
- **Five matches:** `POST /api/free-match/calculate/` → `result_count: 5`,
  all five with image, annual cost and resale populated.
- **One Ride Reveal:** `free_reveal_available: true` → trigger → job
  completed with real Grok content → `free_reveal_used: true`; second
  attempt → 402 `insufficient_credits` with purchase options; endpoint
  hammered 3× — no leak, credits unchanged. All three requirements
  confirmed working as specified.

**Ride Reveal sharing — investigation only (no code change)** · ~1 h
Diagnosed three reported issues; backend verified healthy (share PNGs
generated, `share_image_url` absolute + publicly reachable, 200 image/png):
1. *WhatsApp preview shows no image* — WhatsApp crawls the shared URL for
   `og:image` meta tags; the frontend shares the bare SPA origin, which
   serves generic HTML. Architectural, needs per-URL OG tags (backend-served
   OG page or Vercel edge function).
2. *Copy button copies no reveal link* — confirmed in
   `frontend/src/utils/rideRevealShare.js`: `shareUrl` is
   `window.location.origin`; `resultId` is captured but never used in a URL.
   No reveal-specific URL scheme exists at all.
3. *Recipient flow doesn't exist* — result endpoint is authenticated +
   owner-scoped; no share token or public view. Proposal delivered:
   `share_token` + public `GET /api/ridereveal/share/<token>/` + OG-tagged
   share URL + public viewer page. Awaiting go-ahead.

---

## Deployments (all production, all live-verified after)

| When | What |
|---|---|
| 27-Oct | Search/lookup/dealer batch + image pipeline |
| 28-Oct | Finance block + one-variant filter |
| 29-Oct | GVG garage + Grok estimators + dealer radius |
| 30-Oct | 5-result fixes + Free dial matches + share PNG |
| 31-Oct | Vehicle data audit + Grok fallback + garage integration |
| 1-Nov (2×) | Backfill/perf/provenance batch, then fuel_range alias + estimator fixes |
| 2-Nov (3×) | Polymorphic endpoint batch (incl. the two follow-up consistency fixes) |

## Still open (verified against production, 2-Nov)

1. ~~RideReveal `favorite_color` null~~ — **DONE, verified.** 6 results on
   prod carry a color (e.g. 'Red'), jobs receive it, and the serializer
   returns it end-to-end. The earlier null report predates the fix.
2. **Ride Reveal share flow** — diagnosed 2-Nov (see above); needs the
   share-token + public endpoint + OG-tagged URL work, plus the frontend
   copy-button fix. This is the only functional gap.

## 2-Nov late — Ride Reveal generate response fixes

**Ride Reveal `first_name` missing + `share_image_url` null on completion**
· commits `ff2c902` (code) + `b6295be` (guide) · ~45 min

Two reported bugs from the My Garage reveal flow, both backend root causes:

1. *First name lost* — the frontend already POSTed `first_name` in the
   generate body (`buildGenerateRideRevealBody`), but
   `RideRevealGenerateSerializer` never declared it, so it was silently
   dropped; the share card fell back to the account profile name. Fix:
   `first_name` accepted by the serializer, stored on `RideRevealJob` and
   `RideRevealResult` (migration `0015`), returned in result/job responses,
   and preferred over the profile name on the share card.
2. *`share_image_url` null on completed jobs* — the celery task marked the
   job COMPLETE and saved **before** rendering the share-card PNG, so any
   poll landing in that window got `status: complete` with
   `share_image_url: null`. Fix: PNG render now runs before the job is
   marked complete, so a completed job's result always carries the URL
   (render failure still never blocks the reveal — returns False, logged).

Verified: 59/59 mygarage tests green (3 new: job stores first_name, result
serializer returns it, share card prefers it). Frontend guide section 4
added; no frontend code change needed (it already sends/reads the fields).
Deployed 2-Nov (4th deploy of the day); live check: generate → poll →
completed job carries `first_name` + non-null `share_image_url`.

## 2-Nov — Uncosted catalogue vehicle cost fill (MyGarage issue #1)

**315 workbook vehicles had no cost data → wrong "Est. Cost Difference"**
· commit `e8a9f2c` · ~3 h

Root cause: the FINAL LAUNCH workbook ships blank cost columns for 315 of
1,829 vehicles (all Aston Martin, Bentley, Ferrari, Lamborghini,
Rolls-Royce, Maserati, Lotus + scattered vans/SUVs). With no stored
`mode_coo_pa`, `calculate_core_rating` fell back to a category-average
baseline, so garage cards showed e.g. "saving $38,925/yr" against a
$58,626 made-up peer average while the "Current vehicle" radio looked
selected (user's current vehicle = 2025 Aston Martin Vantage, itself
uncosted → $0/yr).

Fix: `apps/vehicles/services/uncosted_estimates.py` — re-implements the
workbook Formulas tab step-for-step (§1-9) on top of the already-imported
platform tables (fuel/elec prices, CTP, insurance, rego, maintenance,
tyres, km, finance, depreciation L1-L3, CategoryScoringBounds latest
version) plus sheet constants only the workbook carries (FUELEF 2.9/3.39
kg/L scope 1+3, grid scope-3 factors, CO₂ cap 315/250/190, 0.8/0.2
weights). Fallbacks, per the DB → defaults hierarchy: sibling-variant
driveaway when the row has no price (65 vehicles), tailpipe-derived or
category-median fuel consumption (103 vehicles), 18 kWh/100km platform
flat for missing EV consumption. Every filled mode dict is marked
`costing_basis: sheet_defaults_v6.4` and the vehicle's `assumption_fills`
records what was estimated.

Command: `fill_uncosted_vehicle_estimates [--commit] [--limit N]
[--vehicle-id]`. Run on prod 2-Nov: **177 filled, 138 skipped** (no price
anywhere in the catalogue — Sprinter/Continental GT/Vito/Crafter/Iveco
etc.), 0 failed; idempotent (second run = no-op). 8 new tests; vehicles
suite 170 green.

Live verified (carreb1@yopmail.com): Aston Martin Vantage now rates
2.0★ The Detour™ Pure Cost $5,991/yr / 3.0★ True Value $48,241/yr;
ZEEKR 009 card diff = **"Est. $28,539/yr saving, comp: current_vehicle"**
vs Aston — was $38,925 vs category average.

Still open (investigated, not approved for change): CORE dial arc
min/max from `CategoryScoringBounds` (dataset API exposure + frontend
needle), and priority slider having no effect on stored workbook scores
(`rating_engine` line ~413 discards it by design).

## 3-Nov — Vehicle Lookup showed catalogue cars as "AI Estimate"

**2026 Bentley Bentayga (and any trim-searched car) came back source=ai,
wrong price, CORE 0.0** · commit `282d073` · ~1.5 h

Root cause: Vehicle Lookup sends the picked trim in the search query
(`2026 Bentley Bentayga Azure`), but `CurrentVehicleSearchView`'s text
filter only matched brand/model. One trim word ("Azure") zeroed the
catalogue queryset → the strict-match check failed → the Grok fallback
**replaced** the entire response with an AI guess card. The AI card
carries no rating (0.0) and its price was inherited from a row that
itself borrowed the 2025 Bentayga Hybrid's $405K during the 2-Nov
uncosted fill (sibling fallback; flagged in `assumption_fills`).

Fix (`apps/mygarage/views.py`):
- `text_filter` now also ORs the `variant` field into each query word.
- When strict matching fails, AI cards are **appended after** any
  catalogue/GVG rows (deduped by make/model/variant/year identity key)
  instead of replacing them. DB-empty behaviour unchanged (AI still
  answers "toyota camry 2015"-style queries).

Tests: 2 new in `CurrentVehicleSearchAIFallbackTests`
(trim-word query → catalogue row, AI never called; AI appended behind DB
rows, never in front). mygarage suite 61/61 green. Live-verified in the
prod container before deploy: "2026 Bentley Bentayga Azure" → carreb
Bentayga Azure first; "toyota camry 2015" → GVG rows + AI appended.

Data note for next sheet refresh: the imported 29-Oct FINAL LAUNCH
workbook deliberately carries **no** Bentayga price (data rule 4.2 —
price type "n/a, no Australian price published"). The $438K the user
sees must be in a newer Drive version; re-export + re-import would bring
the real price. The 65 sibling-priced rows from the 2-Nov fill are kept
(so costing works) but flagged in `assumption_fills`.

## 3-Nov — Free plan garage cap corrected to 5 vehicles

**Free users were blocked from adding a 2nd vehicle to My Garage**
· commit `f3ec8ae` · ~30 min

Root cause: `PLAN_LIMITS[FREE] = 1` in `apps/mygarage/services.py`. Setting
a current vehicle also creates a garage row, so a new free user hit the
cap with their first vehicle and every further add returned 403 "allows
1 vehicles". Agreed Free plan = 1 current vehicle + up to 5 vehicles in
My Garage (current vehicle occupies one of the 5 slots).

Fix: FREE limit 1 → 5. This one table drives both the garage add
endpoint and the Free Match save cap, so both now agree. New regression
test: 5 adds succeed, 6th refused; mygarage suite 62/62 green. Deployed
and live-verified on prod with a throwaway free account (temp rows
deleted): current vehicle 200, second garage add 201, cap_counter
`used 2 / limit 5 / Free`.
