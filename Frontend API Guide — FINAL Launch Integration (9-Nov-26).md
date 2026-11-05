# Frontend API Guide — FINAL Launch Integration (Mon 9-Nov-26)

**For:** Meenam / Abdullah (frontend) · **From:** Ali (backend)
**Backend:** launch dataset `v6.4-audit-04Nov26` (04-Nov FINAL LAUNCH), live on `api.carreb.com.au`.
**Backend commits:** `e8c78ae`, `34930f1`, `be37019`, `e377da5`, `3d09cdc`, `7c39d8c`, `d85252e`. 275+ tests green. Every payload below was captured live from production on 5–6 Nov.

This is the frontend half of the launch bug register (B-01 to B-36), written as a manual: each section is one FE-owned item with the exact payload keys, display rules, curls, and — new in this final version — the **precise file:line in your repo** that needs to change, based on a full audit of `frontend/src` done 6 Nov (Appendix A has the complete audit table).

Golden rule throughout: **render what the payload says, never hard-code** — band names, km copy, ratings, defaults all come from the API.

---

## Launch checklist (the 9 must-dos, in dependency order)

| # | Item | Register | Where (your repo) |
|---|---|---|---|
| 1 | Refetch after Edit Vehicle save **and** reset | B-21 | `pages/MyGarage/GaragePage.js` `handleSaveVehicleDetails` / `handleRevertVehicleOverrides` |
| 2 | Bind km line to `engine_data.costed_km` + caption + D22 badge | B-21/B-02 | `utils/myGarageMappers.js` (`annualKm`), `pages/MyGarage/components/VehicleCardFilled.js` |
| 3 | CO₂ row: prefer `co2_energy_cycle_g_per_km`, fix label | B-04/B-09 | `utils/myGarageMappers.js` (`co2PerKm`, 3 call sites), `VehicleCardFilled.js` |
| 4 | Held cars: amber notice + "Default" badges from `is_suppressed` / `field_sources` | B-22/B-23 | search/select flow + Edit Vehicle form |
| 5 | Badge arcs from `core_arcs.needle` | B-15/B-28 | `pages/MyGarage/components/CoreRatingBadge/` |
| 6 | Est. Cost Difference: sign + word + colour, one component | B-34 | wherever `formatEstCostDifferenceDisplay` renders |
| 7 | Ratings: one decimal, per-mode `core_rating_1dp`, null → "—" | B-20/B-32 | `utils/myGarageMappers.js:325` and every badge/finder/modal |
| 8 | Hide Category Avg. toggle | B-19 | MyGarage card toolbar |
| 9 | Refetch hero after any garage change | B-08/B-21 | same fix as #1 (`refetchSavingsSummary`) |
| 10 | Needle 0 → ~3% stub on both arcs (not empty) | B-37 | `pages/MyGarage/components/CoreRatingBadge/` arc renderer |

---

## 1. km basis — `costed_km`, copy line, D22 badge (B-21, B-02 — updated 6-Nov per Jock)

**km p.a. is a direct user input only.** The odometer-derivation path (odometer ÷ years since purchase) was **retired 6-Nov**: it assumed the car was bought new and overstated on every used car, and out-of-range readings fell back to default silently. Odometer and purchase date stay on the vehicle, optional, and feed **resale only** — they no longer move any cost figure.

Every `engine_data` **and** `meta` on current-vehicle and garage-card payloads carries:

```json
"costed_km": 12100,
"costed_km_source": "default",          // "default" | "user" — no "odometer" anymore
"costed_km_copy": "Costed at 12,100 km/yr (ABS 2020). Change in Edit Vehicle.",
"personalised_estimate": false
```

**Where the number comes from** (backend resolves live):
1. `user` — km the user typed in Edit Vehicle.
2. `default` — ABS 2020 national figure, 12,100 km/yr. Nothing else derives km.

**What to build:**
- The card's km line and the "based on X km p.a." note must read **`engine_data.costed_km`** — NOT the dataset `annual_km` (that stays 15,000 on the 009 forever). Today `myGarageMappers.js:898` resolves `annualKm` from `annual_km`/`estimated_km_pa` only — add `engine_data.costed_km` as the first source for display.
- Always render `costed_km_copy` as the one-line caption under the dollar figures (per card-copy spec).
- When `personalised_estimate: true` (source `user`), also show the D22 badge: **"Personalised estimate based on your inputs and Carreb's assumptions. Not a guarantee."**
- Edit Vehicle: km field **pre-filled 12,100 with the "Default" badge** (B-22 held-car style); once the user edits it, badge the field amber **"Your input"** (B-02) and send `garage_km` in the save payload. **Typing cap 60,000 km/yr** (backend rejects outside 3,000–60,000 with 400).
- Odometer + purchase date fields remain in the form, optional — label them as feeding the resale estimate only. Saving them no longer changes any cost line.
- One edit updates every card (backend computes live per request — see §4 for the refetch you must do).

```bash
# Set km explicitly
curl -X PATCH "https://api.carreb.com.au/api/my-garage/priority-state/" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"garage_km": 20000}'
# Back to the ABS default
curl -X PATCH "https://api.carreb.com.au/api/my-garage/priority-state/" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"garage_km": null}'
```

**Post-launch (patch 1, Abdullah):** move the km control to the MyGarage header beside Mode, labelled **"Your km a year"**, with the line **"Changes cost estimates. Ratings use standard km."** (D29/D30: stars, Dial and bands stay on dataset km.) Same `garage_km`, same PATCH — only placement changes.

**Live proof** (QA account, 009 as current vehicle, `garage_km` 20,000 entered directly): fuel, tyres, servicing, total and CO₂ scale ~×1.65 from the 12,100 baseline — and a second garage car (GAC M8) re-costs at the same 20,000 automatically (Proof 3 re-run, 6-Nov).

## 2. CO₂ row — energy-cycle headline (B-04, B-09)

Render `engine_data.co2_energy_cycle_g_per_km` as the g/km headline for **all** powertrains. `tailpipe_co2_g_per_km` is 0 for every BEV by definition — your mapper currently prefers it (`myGarageMappers.js:1328`, `:1581`, `:365`), which reproduces the "~0 g/km" bug on garage cards (the vehicle slider already does this right — copy that). Example (009): `130.7 g/km` with `annual_co2_kg: 1582` at 12,100 km.

Label the kg line **"energy-cycle, incl. fuel production"** (D39 basis) — `VehicleCardFilled.js:84` currently hard-codes "(rated · combined)"; change it. One basis, labelled — never mix bases on one card.

## 3. Held (suppressed) cars — amber notice + "Default" badges (B-22, B-23)

Type-ahead now includes held cars; every card/suggestion carries `"is_suppressed": true|false` (your codebase has zero references today).

- `true` → amber notice (Figma 10763:97340): **"Official data for this vehicle is incomplete. You can still add it…"**; user tops up on the Edit screen.
- Held cars have **no price, no CORE rating, no stars** (`driveaway_price_display: null`, `core_rating: null`, `stars: null`). Render "—"/empty states — never "$0" or "CORE 0.0".
- Blank fields arrive filled with category defaults and `field_sources.<field> == "default"` → badge those fields **"Default"** (not the amber notice).
- Held cars never appear in search results, bands, counts, matches or the Dial — backend-enforced, nothing to filter.

```bash
curl -s -X POST "https://api.carreb.com.au/api/my-garage/current-vehicle/search/" \
  -H "Content-Type: application/json" -d '{"query": "aston martin vanquish"}'
# -> "is_suppressed": true, "driveaway_price_display": null, "core_rating": null
curl -s -X POST "https://api.carreb.com.au/api/my-garage/current-vehicle/search/" \
  -H "Content-Type: application/json" -d '{"query": "zeekr 009 awd"}'
# -> false, "$147,247", 4.9
```

Suggestions cascade (`/api/current-vehicle/suggestions/?q=...`) items also include `is_suppressed`.

## 4. Edit Vehicle — refetch after save AND after reset (B-21) 🔴 the live bug

The save/reset API calls are already correct (`api/myGarage.js` → PATCH/DELETE per field). The bug is in `GaragePage.js`: **`handleSaveVehicleDetails` and `handleRevertVehicleOverrides` close the modal and toast, but never refetch.** The backend recalculates everything (verified: insurance edit moves the card to the cent); the screen just keeps the stale render until a full page reload.

**Fix:** after a successful save or reset, refetch and re-render all four surfaces from fresh payloads:
```js
await Promise.all([
  resolveCurrentVehicle(),      // current-vehicle card
  refetchGarageVehicles(),      // every garage card
  refetchSavingsSummary(),      // hero
  refreshCoreDialRatings(),     // Dial baseline (or whatever refreshes the Dial)
]);
```
(`refetchGarageVehicles` and `refetchSavingsSummary` already exist in `GarageContext` — see lines 660/648; `resolveCurrentVehicle` is the CV loader.) Edited fields then show the amber "Your input" badge; unedited keep "Default" — use the response's `overrides` block to decide per field.

```bash
curl -X PATCH "https://api.carreb.com.au/api/my-garage/current-vehicle/details/" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"field_name": "insurance_override", "override_value": 2500}'
curl -X DELETE "https://api.carreb.com.au/api/my-garage/current-vehicle/override/insurance_override/" \
  -H "Authorization: Bearer <token>"
```

Annual dollars (`2500` = $2,500/yr); the response is the recalculated card (`insurance_annual: 250000` cents) — you can use it directly, but still refetch the list/hero/Dial.

## 5. Est. Cost Difference — one component: sign + word + colour (B-34, supersedes B-07)

`engine_data.est_cost_difference` shape (your `mapEstCostDifference` in `utils/myGarageFormatters.js` already maps this well — the gap is only in rendering):

```json
{
  "value_cents": 132700,
  "value_display": "Est. $1,327/year",
  "direction": "more_expensive",     // "more_expensive" | "saving" | "same"
  "comparison_mode": "current_vehicle",
  "baseline_cost": 505800,
  "baseline_cost_display": "Est. $5,058/year",
  "est_5yr_savings": 663500,
  "savings_bucket": null
}
```

Gio's 5-Nov convention — ONE component used on every surface (garage cards, Dial band list, hero):

- `direction: "more_expensive"` → **"+$1,327/yr more"** in **amber**
- `direction: "saving"` → **"−$1,327/yr less"** in **green**
- `direction: "same"` → **"$0/yr"**, neutral
- Beneath: **"from your [year make model]"** — G-134.
- Tooltip everywhere (CD-04/CC-03, updated 5-Nov 16:35): *"Estimated yearly cost difference from your current car. + means it may cost more to run, − means it may cost less."*

No bare unsigned figure anywhere; no doubled "Est.". (BE will add `signed_value_cents` = card − current if you prefer not to derive the sign from `direction` — either works.)

## 6. Hero line (B-08, B-34)

`GET /api/my-garage/savings-summary/` returns:

```json
{
  "message_variant": "savings_available",   // or no_current_vehicle / no_garage_vehicles / no_savings_available
  "current_vehicle_annual_cost": 505828,
  "best_garage_vehicle_id": "<uuid>",
  "max_potential_annual_savings": 74300
}
```

`max_potential_annual_savings` is **per-year cents**, same km and mode as the current vehicle, capped at the largest real difference. Render per year; drop "save up to" (banned); no doubled "Est."; name the baseline. Copy shape (Gio signs off): *"Switching to the lowest-cost car in your budget band could potentially lower your estimated running costs by about $743 a year."* Render the matching empty states for the other `message_variant`s — and refetch this endpoint after every garage change (see §4).

## 7. Ratings — one decimal, per-mode, null → "—" (B-20, B-32)

- Bind every rating text to `core_rating_1dp` for the user's **state and mode** (in `vehicle_data.core_ratings.modes.<B|E|C|F>` for garage cards), formatted to exactly one decimal. Never print the integer `stars` as the rating. `myGarageMappers.js:325` currently reads top-level `core_rating` (Pure Cost only) — switch to the per-mode value.
- Star row comes from `stars` / `band_name` beside it. A **null** rating renders **"—" and no stars** — never "0.0" with a filled row. (True 0.0 rows are dataset outcomes; leave them.)
- Audit every surface: garage card badge, finder cards, results modal, hero, RideReveal. The vehicle slider (`vehicleSliderMappers.js:83`) already picks `core_rating_1dp` — that's the pattern.

## 8. Category Avg. toggle — hide it (B-19)

No spec exists for a category-average baseline on cards (Gio, 3-Nov). **Remove/hide the toggle for launch**; cards show the current-vehicle figure only. No card may ever show "—" for Est. Cost Difference while a current vehicle is saved.

## 9. Smart Car Finder headers (B-14, B-33 — backend filter fix lands before 9 Nov)

Backend is adding the budget ceiling, the star filter (G-146) and the downward-only relaxation ladder to `GET /api/vehicles/`. Your side of the contract:

- Header when filters apply strictly: "Showing N of M matches" (Patch 6.4.1).
- When relaxed: same header **plus one line naming what was widened** ("Fewer than 5 under your budget, so we widened down to $X"). Relaxation is **downward only, never above budget**.
- Drop "based on what you told us" / "closest CORE™ matches" copy when nothing was relaxed; never render "0 matches".
- One-decimal ratings on result cards (§7). No "best" wording (G-183).

## 10. Results modal — variant line wraps (B-25)

In the Dial band results modal ("Showing top 10 of …"), remove the single-line ellipsis (`text-overflow`/`white-space: nowrap`) on the variant element; let it wrap to a second (third if needed) line; the card grows with it. Title and variant read as one identity: "2027 Land Rover Range Rover Evoque" / "Range Rover Evoque Hoxton Edition Black". Verify at 1280 px and 390 px.

## 11. Vehicle images (B-10, B-26, B-30)

- **Nearest-year photo:** after an exact make/model/year image miss, pick the closest year for the same make and model (prefer nearest earlier, then later). Catalogue keeps exact-match. (009 saved as 2025 shows the 2026 photo.)
- **FCAI silhouettes:** any vehicle without a photo shows the FCAI silhouette for its `fcai_category` + body type — the 38-PNG set (Corolla: Small Category Sedan; 009: People Movers). Delete the lime-outline and black-van assets. Set is in the backend repo at `docs/Tier 3 Images - FCAI Vehicle Silhouette Images NEW CARS/`.
- **Background:** one plain panel behind every vehicle image; remove the split white/grey. Rounded image container at the card radius (post-launch, per Bohdan).

## 12. CORE badge arcs — `core_arcs` payload, endpoints, curls (B-15, B-28)

**What changed in the API:** every garage surface's `vehicle_data` gained `core_arcs`, and from 6-Nov (`d85252e`) `GET /api/vehicles/<id>/` returns it for **catalogue ids too** — same block, same rules. Purely additive; nothing removed or renamed. The arcs never react to km edits or overrides (dataset values; bounds version `v6.4-audit-04Nov26` first — same table the stars use, so arcs always line up with stars, D29/D30).

**Endpoints** (all live):

| Endpoint | Auth | Where `core_arcs` sits |
|---|---|---|
| `GET /api/vehicles/<id>/` — catalogue and GVG/AI ids | none | **top level** (use `?state=`; default NSW) |
| `GET /api/my-garage/current-vehicle/` | Bearer | `vehicle_data.core_arcs` |
| `GET /api/my-garage/vehicles/` (list) | Bearer | each item's `vehicle_data.core_arcs` |
| `GET /api/my-garage/vehicles/<id>/` | Bearer | `vehicle_data.core_arcs` |
| `POST /api/my-garage/current-vehicle/search/` | none | each result card (top level) |
| AI Smart Match / Free Match cards | mixed | each match card |

**Shape** (real response, 2026 ZEEKR 009 AWD 6-seat, NSW):

```json
"core_arcs": {
  "km_pa_used": 15000,
  "modes": {
    "B": {
      "cost_arc": {"value": 5410.37,  "min": 4676.56,  "max": 7113.36,  "needle": 0.3011367367038738},
      "co2_arc":  {"value": 130.7,    "min": 159.5,    "max": 299.33,   "needle": 0.0}
    },
    "E": { "cost_arc": {"value": 11551.84, "min": 8122.18, "max": 11864.22, "needle": 0.9165}, "co2_arc": {"value": 130.7, "min": 159.5, "max": 299.33, "needle": 0.0} },
    "C": { "...": "True Value — same four keys per arc" },
    "F": { "...": "Full Picture" }
  }
}
```

- Modes: `B` = Pure Cost, `E` = COOL Choice, `C` = True Value, `F` = Full Picture — same letters as `mode_data_by_state`. Mode switching is client-side: read the block for the mode on screen; no refetch.
- `cost_arc.value` = Mode COO p.a. (dataset $); bounds = `cat_min_coo`/`cat_max_coo` for the car's `fcai_category` × mode.
- `co2_arc.value` = energy-cycle g/km (= `co2_energy_cycle_g_per_km`); bounds in g/km too. If your arc draws annual kg, convert bounds: `× km_pa_used / 1000`.
- `needle` = (value − min)/(max − min), clamped 0–1, above max pins at 1.0. **Draw the fill straight from `needle`** — never recompute, never clamp again.
- **Needle 0 → minimal stub (B-37, Jock's ruling 5-Nov):** a `needle` of exactly `0` means the car sits **below the class floor** — every BEV does this on `co2_arc`, because the CO₂ bounds come from the class's fuel-burning cars only (Formulas §7.3; bounds unchanged, spec unchanged). It does **not** mean "no data". Render a **minimal stub, about 3% of the arc length, on both arcs** (cost and CO₂ alike), with the figures shown exactly as now. A genuinely empty arc only happens when `needle` is `null` (Category "Other", see next bullet). Backend will not change; this is display-only.
- Category "Other" (109 listings) has no bounds row → `min`/`max`/`needle` are `null`: figures only, no arcs (until G-185).
- Convention: a low value is a **short arc on both arcs** (Decision E). Badge figures = dataset Mode COO p.a. and annual CO₂ kg for the mode/state on screen.

**Curls:**

```bash
# Vehicle detail (catalogue id) — top-level core_arcs
curl -s "https://api.carreb.com.au/api/vehicles/2f6beb87-aa31-4496-bb17-39cc58839ce9/?state=NSW" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d['core_arcs'], indent=1))"

# Current vehicle (auth)
curl -s "https://api.carreb.com.au/api/my-garage/current-vehicle/" \
  -H "Authorization: Bearer <token>" | python3 -m json.tool | less

# Garage card list (auth) — one line per card
curl -s "https://api.carreb.com.au/api/my-garage/vehicles/" \
  -H "Authorization: Bearer <token>" | python3 -c "
import json,sys
for v in json.load(sys.stdin)['vehicles']:
    print(v['vehicle_data']['name'], v['vehicle_data']['core_arcs']['modes']['B'])"

# Search cards (no auth)
curl -s -X POST "https://api.carreb.com.au/api/my-garage/current-vehicle/search/" \
  -H "Content-Type: application/json" -d '{"query": "zeekr 009 awd"}' \
  | python3 -c "
import json,sys
for r in json.load(sys.stdin):
    print(r['name'], r['core_arcs']['modes']['B']['cost_arc'])"
```

**Layout (B-28):** centre each figure in its band, space the unit ("11,755 kg/yr"), keep ⓘ off the figure line — one badge-level ⓘ at a corner opening the two-line CC-01 tooltip (Bohdan's Fig. 12). Minimum font size; test with a $100,000+ cost at card width and 390 px.

**MyGarage impact:** none on calculations — `total_annual_cost`, `mode_annual_costs`, `est_cost_difference`, ratings and stars are untouched. Display-only.

## 13. Tooltips — paste from the approved file (B-29)

- Paste **Dev paste** blocks 1–6 and 9 character-for-character (column H "NEW TEXT"), `{state}`/`{date}` resolved. FB-01 is the fallback for any label without an entry; no empty ⓘ.
- CD-04 and CC-03 carry the B-34 sign convention (updated 5-Nov 16:35, Flag 15) — use those, not the old "minus means more".
- Fix the two known gaps: the Driveaway ⓘ key lookup (Flag 3) and the hard-coded "Est. Driveaway Price · QLD" label (Flag 2 — resolve the user's state from their profile).
- 5★ band: render `band_name` from the payload (**"Every Day Legend™"**, slug `every-day-legend`) — never hard-code "Everyday Legend" or "Net Zero Ninja" (Flag 7).
- Blocks 7 and 8 are Figma-only, post-launch.

## 14. RideReveal (B-16, B-17, B-35, B-36)

- **Modal:** disclaimer line under the card; headline "{First name} {Archetype}!" resolved from the **current profile** at display time ("You" only when blank); colour row with swatch whenever a colour is stored; plate and colour editable from the modal (BE PATCH re-renders the PNG — no new generation, no credit).
- **Card graphic:** photo fills the rounded frame edge-to-edge (`object-fit: cover`, `overflow: hidden`, centred) — no frame gradient at corners; same on the 1080 share PNG. Plate template follows the user's state or carries no state name.
- **Share (B-36):** every share carries the card image (1080 PNG with footer strip: logo, carreb.com.au, "For entertainment and educational purposes only"), the caption, and a link landing on that RideReveal's public page (BE serves the result page with og:image per `result_id`). Mobile: Web Share API with the PNG file. Desktop: per-channel intents with the result URL. Download fallback for Instagram. Copy link copies the result URL.
- Text guardrails are backend-side (banned wording, one rewrite then job failure + credit refund); render stored fields as-is.

## 15. Manual-entry extras (B-03, B-02)

- Add an **optional purchase price** field to the manual path. Blank → BE falls back to catalogue driveaway badged "Default"; no base → render "Add your purchase price" instead of a figure.
- Odometer + purchase date stay optional and feed **resale only** (§1) — they no longer derive km; pre-fill the km field with 12,100 badged "Default".

## 16. MyGarage match cards (B-31)

- Match cards come only from live rows of the current load, one per listing, never from the current-vehicle record (backend-enforced; if you ever see the CV as a match card, flag it to BE).
- Strip a duplicated make from the model string ("2025 ZEEKR ZEEKR 009" → "2025 ZEEKR 009").
- After re-render, spot-check driveaway, COO, range, resale against the 04-Nov file.

## 17. Favicon / manifest / JSON-LD (B-24)

rel="icon" PNGs at 48/96/192 px, favicon.ico with 16/32/48 frames, `logo` in the Organization JSON-LD (512 px), manifest name "Carreb" / short_name "Carreb", JSON-LD description "Editorially independent vehicle cost-of-ownership estimates for Australian new-car buyers.", social handles into `sameAs`, bump `?v=3` on icon links. QA: curl each icon (200, image/png, pixel size) + Rich Results test.

---

## Appendix A — FE code audit (6-Nov, against `frontend/src` in this repo)

What already works 🟢 / what's missing 🔴, with file:line:

| Area | Status | Evidence |
|---|---|---|
| est_cost_difference mapping | 🟢 solid | `utils/myGarageFormatters.js` `mapEstCostDifference` handles object + `direction`; render layer still needs the B-34 sign/word/colour |
| Dollar figures (breakdown/total) | 🟢 mapped | `myGarageMappers.js` reads `annual_cost_breakdown`/`total_annual_cost` |
| Slider ratings + CO₂ | 🟢 correct | `vehicleSliderMappers.js:47` (`co2_energy_cycle_g_per_km`), `:83` (`core_rating_1dp`) |
| Refetch after Edit save/reset | 🔴 **missing — live bug** | `pages/MyGarage/GaragePage.js` `handleSaveVehicleDetails` (~:595), `handleRevertVehicleOverrides` (~:626): no refetch; `refetchGarageVehicles` only called at :716 |
| km display (`costed_km`) | 🔴 missing | zero matches for `costed_km`/`costedKm` repo-wide; `myGarageMappers.js:898` `annualKm` uses dataset `annual_km`; `VehicleCardFilled.js:74` note + `:89` stat row inherit that |
| km caption + D22 badge | 🔴 missing | zero matches for `costed_km_copy` / `personalised_estimate` |
| CO₂ row on garage cards | 🔴 wrong field | `myGarageMappers.js:365`, `:1328`, `:1581` prefer `tailpipe_co2_g_per_km` → BEVs render ~0; `:84` label hard-coded "(rated · combined)" |
| Held cars | 🔴 missing | zero matches for `is_suppressed` / `field_sources` |
| Badge arcs | 🔴 missing | zero matches for `core_arcs` |
| Per-mode one-decimal rating on cards | 🟡 partial | `myGarageMappers.js:325` uses top-level `core_rating` (Pure Cost only), not `core_rating_1dp` per mode |

## Appendix B — Quick verification curls (no auth)

```bash
# Held vs live current-vehicle search
curl -s -X POST "https://api.carreb.com.au/api/my-garage/current-vehicle/search/" \
  -H "Content-Type: application/json" -d '{"query": "aston martin vanquish"}' | python3 -m json.tool | head -20
curl -s -X POST "https://api.carreb.com.au/api/my-garage/current-vehicle/search/" \
  -H "Content-Type: application/json" -d '{"query": "zeekr 009 awd"}' | python3 -m json.tool | head -20

# Suggestions cascade carries is_suppressed
curl -s "https://api.carreb.com.au/api/current-vehicle/suggestions/?q=aston" | python3 -m json.tool | head -30
```

QA anchors from the register: 2026 009 FWD, QLD, Pure Cost = **4.9**; Chery Tiggo 9 Elite FWD **3.6**; BYD Sealion 8 Dynamic FWD **4.5**; LC300 Sahara QLD = 2.5 / 3.9 / 4.2 / 4.2 across B/E/C/F.

---

*Backend contact: Ali. Anything in this guide that doesn't match what the API returns is a backend bug — send the curl + response and I'll fix it.*
