# Carreb v6.4 — Backend Reply to Launch Bug Register (updated 5-Nov-26, 21:00 AEST)

**To:** Jock / Gio · **Re:** "Carreb v6.4 Launch Bug Register" B-01 to B-36 (updated 5-Nov 16:45) + the 4-Nov FINAL LAUNCH dataset email + B-22 held-car rule
**Environment:** `api.carreb.com.au` — dataset `v6.4-audit-04Nov26` (04-Nov FINAL LAUNCH) loaded and live, 29-Oct load retired, every surface on the one load (B-11).

This is a point-by-point reply to the full register. Statuses: **Fixed (BE)** = backend work landed and verified on prod; **FE action** = backend contract already supports it, frontend work remains; **Copy** = Gio; **BE queued** = backend work we still owe before Mon 9 Nov.

---

## 1. Point-by-point status

| ID | Status | Notes |
|---|---|---|
| B-01 Model-year/MY label lookup | **BE queued + FE** | Type-ahead needs to match the user's badge year against either release year or MY model year and label rows "2025 (MY25) ZEEKR 009 6 Seat AWD"; 352-row CSV test list received. Make-case normalisation (ZEEKR/Zeekr) included. No duplicate rows. |
| B-02 Odometer/purchase date unused | **Fixed (BE)** + FE → **superseded by B-38** | ~~`garage_km` is derived from odometer ÷ years since purchase...~~ Retired entirely per Jock 6-Nov — see B-38. |
| B-03 Resale $297 on every car | **Fixed (BE root cause)** + FE | Root cause was an obsolete cents/dollars heuristic applying a ~$594 base — removed (`34930f1`). FE: add optional purchase price to the manual path; blank falls back to catalogue driveaway badged "Default", and "Add your purchase price" when no base exists. 50% retention now comes from the age/segment curve, not a flat value. |
| B-04 EV CO2 ~0 g/km | **Fixed (BE)** | `engine_data.co2_energy_cycle_g_per_km` is the energy-cycle figure for all powertrains (Wh/km × state grid factor); BEVs show their real ~130 g/km. FE renders it as the headline row (B-04/B-09). |
| B-05 972 km range constant | **Fixed (BE)** | The constant came from the same broken heuristic; range now resolves from the dataset record. 009: 582 km WLTP (catalogue tier). Vantage: from the dataset record. Nothing from the AI lookup is stored without a resolving source URL (G-116). |
| B-06 Est. Cost Difference not like-for-like | **Fixed (BE)** | Both sides now at `garage_km`, same mode, same state, same CO2 method; covered by tests (`test_garage_km.py`, mygarage suite). The difference moves when the user changes km (proof 3). |
| B-07 Sign reads wrong way | **Superseded by B-34** | Withdrawn per register amendment 5-Nov; see B-34. |
| B-08 Hero "$64,151/year / save up to" | **Fixed (BE figure)** + FE + Copy | The hero payload (`/api/my-garage/savings-summary/`) returns `max_potential_annual_savings` in **per-year cents**, computed against the current vehicle at the same km and mode — a real garage car, capped at the largest real difference. FE must render it per year (the "$64,151" was a stale/over-unit render) and Copy drops "save up to" per the banned-words list. |
| B-09 CO2 mixes two bases | **BE confirmed** + FE | Every card's CO2 is energy-cycle (D39). FE: label the kg line "energy-cycle, incl. fuel production"; show tailpipe g/km only where the copy file asks for it. |
| B-10 Silhouette although photo exists | **FE** (BE helper exists) | Catalogue ingest already falls back to the nearest model year for images; the current-vehicle card lookup is FE-side — after an exact miss pick the nearest year for the same make/model (prefer earlier, then later). |
| B-11 Cards not on the 29-Oct dataset / two data paths | **Fixed (BE)** | One load on every surface now: `v6.4-audit-04Nov26`. The stale second path is gone with the reload (proof 1 reconciles cards, Dial and all surfaces against the file). |
| B-12 Held car priced from ORC ($3,250) | **Fixed (BE)** | Null maker price = unpriceable. All 35 unpriced held listings carry null driveaway on all 8 states; we never compute ORC-only driveaway, resale or COO from them. Assertion in place: no resale/COO without MSRP > 0. |
| B-13 Cards mix CORE modes | **Fixed (BE)** | Current vehicle is costed in all four modes; each card's difference subtracts the **same mode** of the current vehicle, same state and km (proof 2: differences 743 saving / 1,244 / 22,148 / 26,354 in B/E/C/F). |
| B-14 Finder shows cars above budget | **BE queued** + FE + Copy | Confirmed: `GET /api/vehicles/` today applies brand/model/year/powertrain/body/seats/ANCAP only — no budget ceiling, no star filter, no relaxation ladder. This is backend work we owe before 9 Nov: budget_max hard cap, G-146 filters applied first, then downward-only relaxation in $5k steps with the Patch 6.4.1 "Showing N of M" header contract. FE header/copy per the item. |
| B-15 Badge arcs off bounds | **Fixed (BE)** + FE | CategoryScoringBounds (64 rows, energy-cycle CO2) loaded from the 04-Nov file and set as first-priority for every lookup; `core_arcs` in the card payload carries per-mode `cost_arc`/`co2_arc` with value/min/max/needle (0–1, clamped, above-max pins full). FE binds arcs to the needle; no fixed lengths. Category "Other" (109 listings): fallback = figures only, no arc, until G-185 lands. |
| B-16 RideReveal guard / disclaimer | **BE guard in place** + FE | Generation runs the banned-content guard (research claims, purchase advice, third person, US spellings, performance/emissions claims) with one rewrite then job failure + credit refund. FE: disclaimer line under the card in the modal, footer strip on the 1080 PNG, state-matched or state-neutral plate, "{First name} {Archetype}!" headline. Third-person and "first"-claim rules are in the guard list; we will paste the guard log from three regenerated cards for QA. |
| B-17 Headline "You" / plate & colour | **BE queued** + FE | Traits are stored per result; first name must resolve from the profile at serve/render time ("You" only when blank). BE to add: PATCH plate/colour on an existing result that re-renders the PNG without new generation or credit. FE: editable plate/colour in the result modal, colour row always shown when stored. |
| B-18 Same five trait pills | **Fixed (BE)** (likely unmerged path per register item 8) | Traits are generated and stored per `result_id` (migration in place). We will add the "≥3 of 5 differ from the user's previous card" guard check. |
| B-19 Category Avg toggle shows "—" | **Decision applied** — FE | Per Gio 3-Nov: hide the Category Avg. toggle for launch; cards show the current-vehicle figure only. No BE change for launch; category-average baseline logged as post-launch. |
| B-20 "CORE™ 0.0 with five stars" | **Fixed (BE)** + FE | Card payloads carry `core_rating_1dp` and `stars` for the user's mode and state. Null rating (held/other unpriced) arrives as null — FE renders "—" and no stars, never 0.0 with a filled row. |
| B-21 Edit saves must recompute everything | **Fixed (BE)** — proof 3 | One server-side recompute on save and on reset; overrides now actually feed the cost lines (the bug proof 3 caught — saved-but-ignored insurance/rego/servicing/tyres/resale). Card, hero (`savings-summary`), Dial baseline and every card's difference all read the recomputed figures. D22 badge driven by `personalised_estimate`. **Update 6-Nov (Jock km ruling):** km p.a. is now a direct user input only — derivation retired, see B-38. |
| B-22 One garage km per user | **Fixed (BE)** + FE → **superseded by B-38** | ~~Live since 4-Nov: `garage_km` per user (odometer-derived or ABS 12,100)...~~ Derivation retired per Jock 6-Nov — see B-38; one value per user, scaling unchanged. |
| B-23 Held car as current vehicle, no lookup | **Fixed (BE)** | Type-ahead ignores `is_suppressed`; resolver short-circuits on any catalogue hit (no Guide step, no internet lookup); `SmartMatchQueryLog`/AI not called; blank fields arrive as category defaults with `field_sources == "default"`. Verified with the held 2026 Vanquish (curls below). |
| B-24 Favicon/manifest/JSON-LD | **FE** | Static-site work on www; nothing backend. Follow the item's action list. |
| B-25 Results modal truncates variant | **FE** | Remove the single-line ellipsis on the variant element; let it wrap two/three lines; card grows. |
| B-26 Split white/grey image background | **FE** | Remove the grey panel behind the current-vehicle image; centre on the card background; one treatment for every vehicle image (rounded container post-launch per Bohdan). |
| B-27 1995 Corolla $9,838 + CO₂ ×3 | **BE queued** | We will return the six component lines for that record and reconcile against the 02-file Light/Small QLD rows; anything that is not fuel+CTP+insurance+rego+maintenance+tyres comes out of the running-cost figure (finance/depreciation live only in the mode baseline behind the difference), and the kg p.a. multiplication gets fixed. Component tables for the Corolla + a 2010 Mazda3 in two states to follow. |
| B-28 Badge figures crammed with ⓘ | **FE** (+ Bohdan) | Centre each figure in its band, unit spaced ("11,755 kg/yr"), one badge-level ⓘ (opens the two-line CC-01 tooltip), minimum font size, test with a $100,000+ cost. |
| B-29 Tooltips off the approved file | **FE + Copy** | Copy step for CD-04/CC-03 done 5-Nov 16:35 (Gio). FE: paste Dev paste blocks 1–6 and 9 character-for-character; FB-01 fallback; fix the Driveaway key lookup (Flag 3) and the hard-coded QLD label (Flag 2); rename the 5★ band label (Flag 7) — see naming note below. |
| B-30 FCAI silhouette set | **FE** | Replace bundle silhouettes with the 38 FCAI PNGs keyed by fcai_category + body style; delete the lime-outline and black-van assets. The set is in the repo under `docs/Tier 3 Images - FCAI Vehicle Silhouette Images NEW CARS/`. |
| B-31 Non-catalogue cars as match cards; 009 twice | **BE partial + FE** | All match/band/count queries filter `is_suppressed = FALSE` and the current load; vehicles are deduped to one row per listing at load. Two things remain: (a) BE verify a current-vehicle record can never be written into the match collection / rendered as a match card; (b) FE strips a duplicated make from the model string ("2025 ZEEKR ZEEKR 009"). |
| B-32 Ratings as whole numbers | **Fixed (BE)** + FE | `core_rating_1dp` is in every card, finder and modal payload for the selected mode and state. FE: one-decimal formatting everywhere; never print the integer `stars` as the rating; null → "—". Note the 1,072 true 0.0 / 616 true 5.0 rows are dataset scoring outcomes (Gio's floored-0.0 decision is open — display rule only). |
| B-33 Finder star filter / 0 matches | **BE queued** + FE + Copy | Same root cause as B-14; see above. Star filter (G-146, default exact band pending Gio's confirmation) plus the downward-only ladder land together with the B-14 fix. FE: "Showing N of M" header + widening line; never "0 matches"; one-decimal ratings on result cards. |
| B-34 Sign, word and colour on every value | **FE + Copy** (BE offers helper) | The payload's `est_cost_difference` carries `direction` ("more_expensive" / "saving" / "same") and `value_cents` (unsigned) — enough for FE to render "+$X/yr more" (amber) / "−$X/yr less" (green) / "$0/yr" with "from your [year make model]" beneath, on cards, Dial and hero, from one component. On request we add `signed_value_cents` (card − current) so FE doesn't derive the sign. Copy: CD-04/CC-03 updated wording done 5-Nov. |
| B-35 RideReveal photo rectangle | **FE** | object-fit: cover, overflow hidden, centred, in the modal and the PNG renderer. |
| B-36 Share sends bare link | **BE queued** + FE | BE: host each result's PNG at a stable URL and serve a public result page per result_id with og:image = the PNG, og:title = headline, disclaimer. FE: Web Share API with the PNG file on mobile; per-channel intents with the result URL on desktop; download fallback for Instagram. |
| B-37 CO₂ arc empty on BEVs (new, from the arc investigation) | **Decision — FE only** (Jock, 5-Nov) | The empty green arc is the formula working: CO₂ bounds come from the class's fuel-burning cars only (Formulas §7.3, deliberate since D39 deleted the BEV hard-set), so every BEV sits below the class floor and its needle clamps to 0. Verified the bounds are identical across every v6.4 batch (21-Oct → 04-Nov) — not a regression. Stars are unaffected (below-min clamps to a 1.0 emissions score). Options A (recompute bounds — refreezes scoring) and B (pin full — reads as highest emitter) are both rejected. **Ruling: FE renders a needle of exactly 0 as a minimal stub, about 3% of the arc, on both arcs; figures shown as now.** No bounds change, no spec change, no backend change. Noted in the FE integration guide §12 (item 10). |
| B-38 Odometer derivation retired — km p.a. is a direct user input only (Jock, 6-Nov, replaces the A/B/C options) | **Fixed (BE)** — Proof 3 re-run below | The 009 case exposed the design flaw: odometer ÷ time since purchase assumes the car was bought new, so it overstates on every used car — the 60,000 km/yr ceiling only caught the extreme, and the silent fallback to 12,100 was the symptom. **For launch:** `resolve_garage_km` now returns the user's Edit Vehicle `garage_km` or the ABS 2020 default — nothing else. `annual_km_from_odometer`, `_coerce_purchase_date` and the ownership/rate guard rails are deleted (net code removal); the old rail bounds live on as the Edit Vehicle typing cap (3,000–60,000, unchanged). Odometer and purchase date stay on the vehicle, optional, feeding resale only. B-22 scaling unchanged: one value per user, fuel/energy/tyres/servicing/CO₂ only, ratings/stars on dataset km (D29/D30). `costed_km_source` is now `default` or `user` only. FE (launch): km field pre-filled 12,100 badged "Default", amber "Your input" once edited, cap 60,000; odometer/date fields stay, labelled resale-only. **Post-launch (patch 1, FE/Abdullah):** km control moves to the MyGarage header beside Mode, "Your km a year" + "Changes cost estimates. Ratings use standard km." — same `garage_km`, same PATCH, placement only. |

**Band naming note (Flags 7/15 + your earlier message):** "Net Zero Ninja" is retired; the 5★ band is **"Every Day Legend™"** (`band_slug: every-day-legend`). Some dataset rows still carry the old "Everyday Legend™" spelling; the FE should always render the `band_name`/`band_slug` values from the payload, not hard-coded strings, so the rename propagates everywhere from one place.

---

## 2. Dataset load — done and reconciled (B-11)

- Loaded 04-Nov FINAL LAUNCH: **1,776 vehicles** (1,777 listings; two LDV G10 Van 2025 rows are identical on Make/Model/Variant/Year and merge to one vehicle), **1,640 live / 136 held**, **59 live makes**, scoring version `v6.4-audit-04Nov26` throughout. (137 held *listings* = 136 held *vehicles* after the merge.)
- Exactly **35 held listings carry no maker price** — `driveaway_price_by_state` is null-valued on all 8 states and `price_basis` says "n/a — maker publishes no Australian price" (B-12 ✓).
- All 136 held vehicles have null COO / resale / rating / stars in DB, verified against the file (B-23 ✓).
- **20 removed listings retired** — none were referenced by any user; deleted. 33 stale rows from the 7-Oct load (all referenced by users' garages) are suppressed, not deleted, so those users' cards keep working.
- Canonical scores (7,104 records), CategoryScoringBounds (64 rows) and the CORE Dial (12,248 rows, 8 states) rebuilt from this file; the new bounds version leads every card arc/rating lookup.
- MD5 note: our file's MD5 is `6a7978e4a15e9a6dceef0adfca61f8a4` vs the `e4f45e…` published in your email — all content checks (counts, held rows, version, removed tab) match your description exactly, so we believe the file is right; please confirm how the published hash was computed.

**Proof 1 — 20 listings × 8 states × 4 modes reconciliation: 640/640 cells match the file (100%), zero mismatches.** Full log: `proof1_reconciliation.log`.

## 3. The three Friday proofs — ALL PASS

### Proof 2 — ZEEKR 009 as current vehicle, like-for-like in all four modes ✓ (`proof2_009_modes.log`)

| Mode | Card total | Est. Cost Difference | Baseline (same mode) |
|---|---|---|---|
| Pure Cost | $5,058 | $743 saving | $5,802 (People Mover avg) |
| COOL Choice | $11,200 | $1,244 more | $9,956 |
| True Value | $22,478 | $22,148 more | $330 |
| Full Picture | $28,619 | $26,354 more | $2,265 |

Card total in each mode equals that mode's own figure; the difference always compares against the baseline in the **same** mode (B-13). Rating/stars follow the mode's dataset value.

### Proof 3 — Vantage edit (insurance $2,500, 20,000 km) + Reset — 13/13 checks PASS ✓ (`proof3_vantage_edit.log`, live 2025 Vantage Coupe on a QA account)

- Baseline → Edit: insurance line **$2,203.04 → exactly $2,500.00**; fuel/servicing/tyres re-scaled to 20,000 km; card total $7,396.33 → $10,400.38; all four mode costs and the Est. Cost Difference moved together; copy became "Costed at 20,000 km/yr, your setting."
- Reset: every figure restored **byte-for-byte**.
- Rating untouched by km throughout (D29/D30 ✓). QA account deleted.

**This proof caught a real bug:** Edit Vehicle's per-line overrides were saved and echoed in the API but never consumed by any calculation. Fixed and deployed (`7c39d8c`).

## 4. Verification curls (all against `https://api.carreb.com.au`)

```bash
# B-22/B-23 — held car findable as current vehicle, flagged, no price/rating, no AI lookup
curl -s -X POST "https://api.carreb.com.au/api/my-garage/current-vehicle/search/" \
  -H "Content-Type: application/json" -d '{"query": "aston martin vanquish"}'
# -> 2026 Vanquish: "is_suppressed": true, "driveaway_price_display": null, "core_rating": null

# Live car unchanged
curl -s -X POST "https://api.carreb.com.au/api/my-garage/current-vehicle/search/" \
  -H "Content-Type: application/json" -d '{"query": "zeekr 009 awd"}'
# -> "is_suppressed": false, "$147,247", 4.9

# B-22 — one garage km updates every card
curl -X PATCH "https://api.carreb.com.au/api/my-garage/priority-state/" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"garage_km": 20000}'
curl -X PATCH "https://api.carreb.com.au/api/my-garage/priority-state/" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"garage_km": null}'

# B-21 — Edit Vehicle override moves the card (response is the recalculated card)
curl -X PATCH "https://api.carreb.com.au/api/my-garage/current-vehicle/details/" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"field_name": "insurance_override", "override_value": 2500}'
curl -X DELETE "https://api.carreb.com.au/api/my-garage/current-vehicle/override/insurance_override/" \
  -H "Authorization: Bearer <token>"

# B-08 — hero figure, per-year cents, same km/mode as the current vehicle
curl -s "https://api.carreb.com.au/api/my-garage/savings-summary/" \
  -H "Authorization: Bearer <token>"

# B-15/B-32 — arcs + one-decimal rating for the mode/state
curl -s "https://api.carreb.com.au/api/my-garage/vehicles/" -H "Authorization: Bearer <token>"
```

## 5. Commits

| Commit | Change |
|---|---|
| `e8c78ae` | B-22 garage km normalisation (garage_km field, per-card scaling, copy lines) |
| `34930f1` | Removed obsolete cents/dollars heuristic (B-03/B-05 root cause) |
| `be37019` | B-22: read odometer/purchase_date from CV overrides (Edit Vehicle path) |
| `e377da5` | B-12 + B-13: held listings suppressed on every catalogue path; same-mode cost differences |
| `3d09cdc` | B-15 + B-22 (4-Nov email): bounds priority `v6.4-audit-04Nov26`; held cars selectable as current vehicle; `is_suppressed` on cards; cache namespace v3 |
| `7c39d8c` | B-21 (proof 3): per-line Edit Vehicle overrides applied to cost lines; fixed-band deltas at costed km; peers don't inherit overrides |

Deployed on `api.carreb.com.au`. **GitHub push done 5-Nov** — everything through `5e672f1` is on `main`: https://github.com/alirehan/Carreb-backend (`1bf9095` was the server-side ref for `7c39d8c` content; that content is in the push). Test suite: 275+ tests green.

## 6. Backend work queued before Mon 9 Nov (our side, no FE dependency)

1. **B-14/B-33** — budget ceiling + star filter on `GET /api/vehicles/`, G-146 filters applied first, downward-only relaxation ladder, Patch 6.4.1 header contract.
2. **B-27** — manual/old-car running-cost reconciliation (six lines only) and the CO₂ kg arithmetic fix, with component tables for QA.
3. **B-01** — keep both years per Guide row; type-ahead/Year select match either; "2025 (MY25)" labels; run the 352-row CSV (352/352 required).
4. **B-17/B-18** — profile first name at serve/render; PATCH plate/colour re-render; trait-uniqueness guard log.
5. **B-31** — assert a current-vehicle record never renders as a match card.
6. **B-36** — stable PNG URL + public result page with og tags.
7. (Optional, on your word) **B-34** — add `signed_value_cents` to `est_cost_difference`.

## 7. Evidence pack

- `proof1_reconciliation.log` — 640/640 cells, 20 listings × 8 states × 4 modes
- `proof2_009_modes.log` — 009 CV, four modes, like-for-like differences
- `proof3_vantage_edit.log` — baseline / edit / reset with 13 PASS checks
- Server-side verification counts: 1,640 live · 136 held · 59 makes · 35 unpriced held · dial batch `v6.4-audit-04Nov26` (12,248 rows)

The frontend integration guide (every FE-owned item above, with payload keys and curls) has been handed to Meenam as a separate document.
