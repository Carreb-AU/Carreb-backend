# Carreb Backend — Reply to Jock (7-Nov-26): Blockers, Your Questions, New Bugs, Everything Shipped

**To:** Jock / Gio · **From:** Ali (backend)
**Environment:** `api.carreb.com.au` — dataset `v6.4-audit-04Nov26`, every surface on the one load.
**Code:** `main` at `fb0e7cd` (https://github.com/alirehan/Carreb-backend). Server is synced and running this build.
**Test suite:** 275+ backend tests green (mygarage 82, vehicles 113+, freematch 8, users 6, billing).

This document answers your 6-Nov reconciliation email end-to-end: each blocker with what we found and the proof, each of your six questions, the two new My Garage bugs fixed yesterday/today, and the additional work done this week (images, dial rebuild, the 502 fix). The FE integration guide for Meenam/Abdullah is a separate document ("Frontend API Guide — COMPLETE Final (7-Nov-26)").

---

## 1. Your 6-Nov blockers — status and evidence

### 1.1 [BLOCKER] 5★ band name inverted — FIXED ✓
You were right. Three hardcoded maps carried the stale label ("Every Day Legend™" / `every-day-legend`). All now emit **"Everyday Legend™" / `everyday-legend`** (`rating_engine.py`, `core_dial.py`, `uncosted_estimates.py`). Verified live on the 009: `band_name: "Everyday Legend™"`, 5.0★ / rating 4.9. FE rule stands: render the payload, never hard-code.

### 1.2 [BLOCKER] GitHub push — DONE ✓
Everything through `fb0e7cd` is on `main`, including the commits the earlier reply listed under the server-only ref (`1bf9095` content was `7c39d8c` — all now in source control).

### 1.3 [BLOCKER] 109 vehicles missing from the CORE Dial — FIXED, with a correction to the diagnosis ✓
The 109 existed — your arithmetic was right — but they are **not "Other" category**. The 04-Nov file has **zero live "Other" vehicles** (the one Other row is held). The actual cause: our dial build had a Research Status gate (`ON_SALE_STATUSES = Confirmed + v6.3.4 seed`) on top of `is_suppressed`. The excluded 109 = **104 "Pending verify" + 5 "Coming FY26"** live cars. Your own locked rule — *"is_suppressed is the only gate"* — said they belong in.
**Fix:** the status gate is deleted. Dial rebuilt live: **13,120 rows / 1,640 listings / 1,640 per state**, verified against the database. Bands, counts and "View … vehicles" lists now include them. (Our earlier "Category Other (109 listings)" note was stale — apologies; there is no live Other card this load.)

### 1.4 [BLOCKER] B-16 guard log — CLOSED, log below ✓
The guard now fires on **all four** rule families (third person, US spelling, advice words, performance claims) plus the original research/emissions rules. The system prompt is tightened: second person, Australian English, no performance claims. Production log:
```
[third person]      FLAG: third person       ✓  "He made the smart choice with his car."
[US spelling]       FLAG: US spelling       ✓  "color", "favorite"
[advice words]      FLAG: purchase advice   ✓  "you should buy", "worth every dollar"
[performance claim] FLAG: performance claim ✓  "fastest", "0-100", "horsepower"
[clean control]     (clean)                 ✓
```
**Plate graphic:** the PNG plate header was hardcoded "WESTERN AUSTRALIA" for every user — that's why the QLD user saw WA. It now renders the user's state (or no state name), verified by test.

### 1.5 [BLOCKER] Suppressed rows as match cards — VERIFIED CLEAN ✓
Every match/band/freematch query filters `is_suppressed=False`; removed listings aren't in the load at all; a current-vehicle record is a different table and structurally cannot render as a match card. "Suppressed, not deleted" only keeps **existing garages'** cards working (B-22/B-23) — those are garage cards, not match cards.

### 1.6 [BLOCKER] Proof 3 skipped the EV case — RUN, PASSES ✓
Off-grid proof on the 009 (set as current vehicle on the QA account):
| Step | g/km | kg/yr |
|---|---|---|
| Baseline | 130.7 | 1,582 |
| Off-grid 50% | **81.7** (= 130.7 × 0.5/0.8) | **989** (= 1,582 × 81.7/130.7) |
| Reset (override deleted) | 130.7 | 1,582 |

The `off_grid_energy_percent` override now replaces the dataset's standard 0.20 off-grid share on the **grid component** of energy-cycle CO₂ (D39 basis): BEVs `×(1−p)/0.8`; PHEVs get the grid component only, fuel untouched. It applies to both the g/km row and the kg p.a. line, on the card and every surface that reads it.

### 1.7 [BLOCKER] B-34 has no neutral — FIXED ✓
`direction` already had a third value, `"same"`, but it fired only on an exact-zero cent difference — effectively never. It now fires whenever the difference **rounds to $0/yr**, so the FE colours nothing on a near-zero: `more_expensive` → "+$X/yr more" (amber), `saving` → "−$X/yr less" (green), `same` → "$0/yr" (neutral).

### 1.8 [BLOCKER] Timing — ALL SIX ITEMS DONE ✓ (before Sunday)
B-14/B-33 finder filters, B-01 MY mechanics, B-27 six-line fix, B-31 verification, B-36 public result page — see §3 and §4. Backend cut-off comfortably met.

---

## 2. Your six questions — detailed answers

**Q1. MD5 mismatch.** Counts, held rows and version all match our load, so a Drive re-save on your side is the most likely explanation — agreed. We'll treat your recomputed hash as canonical; nothing on our side keys off the MD5.

**Q2. B-27 — "queued" or "fixed"?** It was queued when written; it is **fixed now**. The EV road-user charge was being charged to every car via the class median; it is now gated to plug-in powertrains only, so a 1995 petrol Corolla's total is exactly the six lines (fuel + CTP + comprehensive + registration + servicing + tyres). CO₂ audited at the same time: `tailpipe × km / 1000`, no multiplication bug. Locked with tests.

**Q3. B-03 — blank manual purchase price.** The card returns `resale_value_5yr_estimate: null` when there's no base; the FE renders **"Add your purchase price"**. With a base (catalogue driveaway or a user-entered price) resale derives from the age/segment/brand retention formula, badged "Default".

**Q4. B-05 — the 2025 009's 582 km.** The 2025 009 isn't a catalogue row; the card reads the **2026 catalogue record** (nearest-year), so 582 km is the stored WLTP figure, `field_sources: "db"` — a dataset value, not an AI estimate, no "Check this" badge needed.

**Q5. B-11 — the two LDV G10 Van 2025 rows.** Both files contain exactly **one** LDV G10 Van 2025 variant ("Van"; 64 sheet rows = 8 states × 8 mode rows). The merge to one listing was correct — no second variant was lost. (Its dial inclusion now works via the status-gate fix, §1.3.)

**Q6. B-21 — Vantage insurance $1,315 → $2,203.04.** In the **29-Oct file every Aston Martin, including the Vantage, was held**. Held cars get blank fields filled from the category defaults — so $1,315 was the Sports-category default, badged "Default". The **04-Nov file released the Vantage** (your email: "the 2025 Aston Martin Vantage is live in this file"), so it now carries its own insurance estimate, $2,203.04. The insurance inputs are byte-identical between the two files — what moved was the held→live flip.

---

## 3. New bugs fixed — My Garage vehicle eligibility (7-Nov)

Reported yesterday; root-caused to two spots in `apps/mygarage/views.py`; fixed with minimal targeted changes (no migrations, no model changes, AI Search / freematch / Smart Match / garage CRUD untouched).

**Bug 1 — My Garage accepted non-Carreb records.** `POST /api/my-garage/vehicles/` accepted GVG and AI ids (the serializer even re-routed a GVG/AI id sent in the catalogue field into its own field), so vehicles with no record in the Carreb Vehicles table were being inserted.
**Fix:** the endpoint now requires a `vehicle_catalogue_id` that resolves to a real `Vehicle` row — anything else is rejected with 400 *"Only Carreb catalogue vehicles can be added to My Garage."* Pre-existing non-catalogue garage rows still list, edit, override, archive and delete exactly as before.

**Bug 2 — Current Vehicle auto-added to My Garage on every change.** The current-vehicle endpoint created a garage row on **every** save (catalogue, GVG *and* AI), gated only by "not already in the garage"; the `update_or_create` `created` flag was ignored, and the garage cap check even blocked GVG/AI current-vehicle saves when the garage was full.
**Fix:** auto-insertion now requires **both** conditions — (1) the user's **first-ever** current vehicle (`created` from the update), and (2) the vehicle **exists in the Carreb Vehicles table** (id validated before any write; also kills a dangling-FK 500 on bogus ids). GVG/AI/manual current vehicles still save as the Current Vehicle (B-22/B-23 intact) but never reach My Garage; the cap check gates only on a would-be insertion.

**Tests:** the scenario matrix is locked in code — first catalogue CV → garage ✓; first GVG CV → CV saved, no garage ✓; first AI CV → CV saved, no garage ✓; second CV change → no insertion ✓; manual GVG/AI add → 400 ✓; unknown id → 400 on both endpoints ✓; duplicate add → `already_in_garage` ✓. mygarage suite 82/82, freematch + garage-km 38/38. **Deployed live (commit `fb0e7cd`).**

---

## 4. Additional work this week (beyond the register)

- **Vehicle images (B-10/B-30):** full curated set imported from the Drive — 446 PNGs, each verified 1752×1000 against the manifest; **all 1,640 live listings now carry a photo**; 77 held vehicles silhouette-filled; 418 old files deleted; backup kept server-side. The Tier 3 FCAI set (38 PNGs) is in the repo at `docs/Tier 3 Images - FCAI Vehicle Silhouette Images NEW CARS/` for the FE bundle.
- **CORE Dial rebuilt** with the fixed gate (§1.3) — band counts and "View … vehicles" lists have shifted accordingly; re-capture any Dial screenshots.
- **Site 502 fix:** the Bad Gateway episodes were nginx caching the web container's IP at startup — every web redeploy pointed nginx at a dead IP. nginx now re-resolves at request time (Docker DNS, 10s TTL); **future deploys self-heal in ~10 seconds with no manual restart.**
- **B-38 (your km ruling) shipped:** odometer derivation retired — km p.a. is a direct user input only (12,100 ABS default, "Default" badge, "Your input" once edited, 3,000–60,000 typing cap); odometer + purchase date remain, optional, feeding resale only.
- **RideReveal:** public no-auth result page with og tags (`public_url` on the result payload is the share URL); plate/colour PATCH re-renders without credit.
- **Billing:** the profile API now returns the real `next_charge_date` and `cancel_at_period_end` (the FE's "Jan 1, 2027" was a hardcoded placeholder).
- **FE slider CO₂:** the slider read only the fuel component (0 for every BEV) — fixed to fuel + grid; Abdullah's parallel fix would have dropped the grid part for PHEVs, so the merged version sums both.

---

## 5. Commits referenced
`e8c78ae` `34930f1` `be37019` `e377da5` `3d09cdc` `7c39d8c` `d85252e` `c47984d` `6e0a2f9` `b22adaa` (B-38) `f0bbe8d` (6-Nov blockers) `09276cb` (finder/MY/result-page/B-27) `2b73450` (B-16 guard) `8462eb9` (nginx 502) `fb0e7cd` (My Garage eligibility) — all on `main`, all deployed.

## 6. What we need from you
1. **The 352-row MY CSV** never reached us — re-share and I'll run `load_model_year_csv` (dry-run first); the matching/label machinery is already live.
2. Nothing else backend-side. Remaining launch items are FE (see the FE guide): refetch after Edit, km/CO₂ bindings, held-car UI, arcs stub, tooltips paste, and the two new FE items below.

---

*Anything in this document that doesn't match what the API returns is a backend bug — send the curl + response and I'll fix it.*
