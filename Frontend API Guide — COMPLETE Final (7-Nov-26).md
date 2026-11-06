# Frontend API Guide — COMPLETE Final (7-Nov-26)

**For:** Meenam / Abdullah (frontend) · **From:** Ali (backend)
**Backend:** `api.carreb.com.au` — dataset `v6.4-audit-04Nov26`, code at `fb0e7cd`.
**This document supersedes** "FINAL Launch Integration (9-Nov-26)" and "6-Nov Register Amendments" — everything from both is consolidated here, plus the newest changes (garage eligibility, next-charge date, dial at 1,640). If any older guide disagrees with this one, **this one wins**.

Golden rule everywhere: **render what the payload says, never hard-code** — band names, km copy, ratings, directions, dates all come from the API.

---

## 1. Launch checklist (in dependency order)

| # | Item | Where (your repo) |
|---|---|---|
| 1 | Refetch after Edit Vehicle save **and** reset | `pages/MyGarage/GaragePage.js` `handleSaveVehicleDetails` / `handleRevertVehicleOverrides` |
| 2 | Bind km line to `engine_data.costed_km` + caption + D22 badge | `utils/myGarageMappers.js` (`annualKm`), `VehicleCardFilled.js` |
| 3 | CO₂ row: energy-cycle headline; **slider = fuel + grid sum** | `myGarageMappers.js` (3 call sites), `vehicleSliderMappers.js` |
| 4 | Held cars: amber notice + "Default" badges | search/select flow + Edit Vehicle form |
| 5 | Badge arcs from `core_arcs.needle`; **0-needle → ~3% stub** | `CoreRatingBadge/` |
| 6 | Est. Cost Difference: sign + word + colour incl. `$0/yr` neutral | `formatEstCostDifferenceDisplay` render sites |
| 7 | Ratings: one decimal, per-mode `core_rating_1dp`, null → "—" | `myGarageMappers.js:325` and every badge/modal |
| 8 | Hide Category Avg. toggle | MyGarage card toolbar |
| 9 | Refetch hero after any garage change | same fix as #1 (`refetchSavingsSummary`) |
| 10 | **Next charge date from profile** (§3) | `SettingsSubscription` (Abdullah's version landed — verify against §3) |
| 11 | **Garage-add error handling** (§4): 400s are expected now | garage add flow |
| 12 | Finder header contract with `relaxation` block (§9) | Smart Car Finder |

---

## 2. My Garage eligibility — NEW (7-Nov)

Backend now enforces that My Garage contains **only Carreb Vehicles-table records**:

- `POST /api/my-garage/vehicles/` accepts **only** `vehicle_catalogue_id` pointing at a real catalogue vehicle. GVG / AI ids → **400** `{"detail": "Only Carreb catalogue vehicles can be added to My Garage."}`; unknown UUID → **400** `{"detail": "Vehicle does not exist in the Carreb Vehicles table."}`
- Setting a Current Vehicle auto-inserts it into My Garage **only** on the user's **first-ever** CV **and** only for catalogue vehicles. GVG/AI/manual CVs save fine but never auto-appear in the garage.
- Existing garage rows of older non-catalogue types still render/edit/archive normally — don't strip them from the UI.

**FE handling:** catch the 400s on the add call and show the detail message; do not assume a CV change adds a garage card (refetch both lists, per #1).

```bash
curl -s -X POST "https://api.carreb.com.au/api/my-garage/vehicles/" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"vehicle_catalogue_id": "2f6beb87-aa31-4496-bb17-39cc58839ce9", "source": "vehicle_lookup"}'
# 201 -> garage row; repeat -> 200 with "already_in_garage": true
```

## 3. Settings — real next charge date (billing)

`GET /api/users/profile/` (and the PATCH response) now returns:
```json
"next_charge_date": "2027-10-15T00:00:00Z",   // null for free users / nothing on file
"cancel_at_period_end": false
```
- Render "Next charge: 15 Oct 2027" formatted `en-AU` (day month year).
- `next_charge_date: null` → **hide the status bar entirely** (the old hardcoded "Jan 1, 2027" placeholder is gone from the backend contract; if any FE copy of it remains, delete it).
- `cancel_at_period_end: true` → "Subscription is scheduled to be canceled at the end of the billing period."
- **Renew plan** (7-Nov): `POST /api/billing/renew/` (Bearer) makes the Renew button real. Responses:
  - `200 {"renewed": true, "cancel_at_period_end": false, "next_charge_date": ...}` → clear the cancel UI, toast success, refetch the profile.
  - `200 {"needs_checkout": true, "plan_type": "full_insight_pro"}` → the subscription has fully ended; start a fresh checkout for that plan (`/pricing/upgrade/<plan-type-with-dashes>`).
  - `400 {"error": "..."}` → show the message (e.g. not scheduled to cancel / no subscription on file).
- Abdullah's implementation in `userProfile.js`/`SettingsSubscription.js` (presence-aware extraction, nulls, formatter) is the canonical one — keep it; the renew wiring (`token` + `onProfileRefresh` props, `api/stripe.js renewSubscription`) is in place on `main`.

```bash
curl -s "https://api.carreb.com.au/api/users/profile/" -H "Authorization: Bearer <token>" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['next_charge_date'], d['cancel_at_period_end'])"
```

## 4. km basis — direct user input only (B-38, final)

km p.a. is **only** the user's Edit Vehicle value, else the ABS 2020 default 12,100. The odometer derivation is retired (it assumed cars were bought new); odometer + purchase date stay optional and feed **resale only** — label them that way in the form. `costed_km_source` is `"default"` or `"user"` (no `"odometer"` anymore). Typing cap 3,000–60,000 (backend 400 outside). Badges: "Default" on the 12,100 pre-fill, amber "Your input" once edited. `personalised_estimate: true` → D22 badge: *"Personalised estimate based on your inputs and Carreb's assumptions. Not a guarantee."*

```bash
curl -X PATCH "https://api.carreb.com.au/api/my-garage/priority-state/" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"garage_km": 20000}'          # set; null reverts to the ABS default
```
**Post-launch (patch 1):** km control moves to the MyGarage header beside Mode — "Your km a year" + "Changes cost estimates. Ratings use standard km." Same field, same PATCH.

## 5. CO₂ row — energy-cycle, and the slider rule

- Headline g/km for **all** powertrains = `engine_data.co2_energy_cycle_g_per_km` (never `tailpipe_co2_g_per_km` — it's 0 for every BEV). Label the kg line **"energy-cycle, incl. fuel production"**.
- **Slider rule (Jock 6-Nov):** mode rows carry two components — `co2_fuel_g_km` (fuel production) and `co2_grid_g_km` (electricity production). The figure is **fuel + grid** (equals the energy-cycle total). The fuel part alone is 0 for BEVs; the grid part alone is 0 for petrol; a fuel-only or grid-only fallback misreports one powertrain. `vehicleSliderMappers.js` implements this via `resolveModeCo2PerKm` — keep it, and never read one component alone anywhere else.
- The user's off-grid % (Edit Vehicle) scales the grid component: BEV 50% off-grid → 130.7 becomes 81.7 g/km. You just render what's sent.
- Still to fix: `onboardingStep4.js` / `AddVehicleScreen.js` map tailpipe only — same energy-cycle-first treatment.

## 6. Band name — "Everyday Legend™"

The 5★ band is **"Everyday Legend™" (one word)**, slug **`everyday-legend`** (trademark filing confirmed by Jock). Render `band_name`/`band_slug` from the payload on every surface; update the 5★ tooltip heading. Never "Every Day Legend", never "Net Zero Ninja".

## 7. Est. Cost Difference — one component, three states

```json
{"value_cents": 132700, "value_display": "Est. $1,327/year",
 "direction": "more_expensive",          // more_expensive | saving | same
 "comparison_mode": "current_vehicle", "baseline_cost": 505800,
 "baseline_cost_display": "Est. $5,058/year",
 "est_5yr_savings": 663500, "savings_bucket": null}
```
- `more_expensive` → **"+$1,327/yr more"** amber · `saving` → **"−$1,327/yr less"** green · `same` → **"$0/yr"** neutral (fires whenever the difference rounds to $0).
- Beneath: "from your [year make model]" (G-134). Tooltip (CD-04/CC-03): *"Estimated yearly cost difference from your current car. + means it may cost more to run, − means it may cost less."* One component everywhere (cards, Dial band list, hero). No bare unsigned figure, no doubled "Est.".

## 8. Refetch after Edit save AND reset — still the #1 live bug

Backend recomputes everything on save/reset; the screen keeps stale renders because `handleSaveVehicleDetails`/`handleRevertVehicleOverrides` never refetch. After success:
```js
await Promise.all([
  resolveCurrentVehicle(), refetchGarageVehicles(),
  refetchSavingsSummary(), refreshCoreDialRatings(),
]);
```
Use the response's `overrides` block to badge edited fields "Your input" vs "Default".

## 9. Smart Car Finder — filters, relaxation, header contract

New params on `GET /api/vehicles/`: `budget_max`, `budget_min` (dollars), `stars` (1–5, **exact band**: 3 = rating 2.5–3.4), `state` (prices/ratings read for this state, default NSW, Pure Cost basis). `mode_data_by_state` is now in every list result for per-mode one-decimal ratings.

Response (paginated) gains a `relaxation` block — present when `budget_min` was passed:
```json
"relaxation": {"applied": true, "widened": "budget_min",
               "from_dollars": 55000, "to_dollars": 40000, "strict_count": 1}
```
Fewer than 5 matches inside the band → the floor steps down $5k at a time until 5 matches or $0; **the ceiling never moves**. Headers: strict → "Showing N of M matches"; relaxed → same + one line "Fewer than 5 under your budget, so we widened down to $40,000". Never "0 matches"; never "based on what you told us" when nothing relaxed.

```bash
curl -s "https://api.carreb.com.au/api/vehicles/?budget_max=40000&budget_min=25000&stars=3&state=NSW" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['count'], d.get('relaxation'))"
```

## 10. CORE Dial — 1,640 vehicles, arcs, stub

- The Dial now covers **all 1,640 live listings** (13,120 rows). Band counts, percentages and "View … vehicles" lists shifted — re-screenshot; never cache counts client-side.
- `core_arcs` (garage/current-vehicle payloads + `GET /api/vehicles/<id>/` top-level) per mode: `cost_arc` and `co2_arc`, each `{value, min, max, needle}`; `needle = (value−min)/(max−min)` clamped 0–1, above max pins at 1. **Draw the fill straight from `needle`**.
- **Needle of exactly 0 → minimal stub ~3% of the arc on both arcs** (a below-floor car, e.g. every BEV on CO₂ — the bounds come from the class's fuel-burning cars only, by design). Zero does **not** mean "no data". Only `null` (Category "Other", no bounds row) draws no arc — and this load has no live Other vehicles.
- Arc figure = dataset Mode COO p.a. / annual CO₂ kg for the mode+state on screen; arcs never react to km edits.
- Mode letters: `B` Pure Cost, `E` COOL Choice, `C` True Value, `F` Full Picture — client-side switching, no refetch. **Pure Cost rule:** Mode B = the running-cost lines only (fuel/energy, CTP, insurance, rego, servicing, tyres, EV levy) — never finance or depreciation; every dollar surface (card, difference, Dial, hero) pairs the same mode on both sides; ratings/stars always stay on dataset km.

```bash
curl -s "https://api.carreb.com.au/api/vehicles/2f6beb87-aa31-4496-bb17-39cc58839ce9/?state=NSW" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['core_arcs']['modes']['B'])"
```

## 11. Held (suppressed) cars — selectable as current vehicle only

Type-ahead includes held cars; cards carry `is_suppressed`. `true` → amber notice *"Official data for this vehicle is incomplete. You can still add it…"*; no price/rating/stars (render "—", never "$0"/"0.0"); blank fields arrive as category defaults with `field_sources.<field> == "default"` → badge "Default". Held cars never appear in search results, bands, counts, matches or the Dial (backend-enforced).

```bash
curl -s -X POST "https://api.carreb.com.au/api/my-garage/current-vehicle/search/" \
  -H "Content-Type: application/json" -d '{"query": "aston martin vanquish"}' | python3 -m json.tool | head -15
```

## 12. Type-ahead MY labels (B-01)

Badge year and model year can differ (year 2024, MY25). Search + suggestions match a year token against either; cards annotate: **"2024 (MY25) ZEEKR 009 6 Seat AWD"**. Render `name` as sent. (MY values populate when the client's CSV arrives — until then no annotation, which is correct.)

## 13. Vehicle images

- Live now: 446 curated 1752×1000 PNGs; **every live vehicle has a photo** (`image_url` like `/media/vehicle_images/zeekr-009-2026.png` — the filename is a frozen key, never regenerate it from text). 77 held vehicles carry silhouette fills.
- **FCAI silhouettes (B-30):** the 38-PNG set is at `docs/Tier 3 Images - FCAI Vehicle Silhouette Images NEW CARS/` in the backend repo — replace the bundle, keyed by `fcai_category` + body type; delete the lime-outline and black-van assets.
- Nearest-year photo fallback: exact miss → nearest year, same make/model (prefer earlier). One plain panel behind every image; rounded container radius per the card.

## 14. RideReveal

- **Share URL:** the result payload has `public_url` — a public no-auth page with `og:image` (the 1080 PNG) and `og:title` ("{First name} {Archetype}!"). Use it for copy-link and every desktop channel intent; mobile uses the Web Share API with the PNG file; Instagram = download fallback.
- **Plate graphic:** backend renders the user's state on the plate header (the old hardcoded "WESTERN AUSTRALIA" is gone) or no state name — nothing for you to do; verify a QLD user.
- Disclaimer line under the modal card; footer strip on the 1080 PNG; colour row with swatch when stored; plate/colour editable from the modal (PATCH re-renders, no credit). Headline "{First name} {Archetype}!" resolves from the profile ("You" only when blank). Render stored traits/facts as-is — the guard + one-retry is backend-side.

## 15. Ratings, hero, misc (carried forward, unchanged)

- Ratings: `core_rating_1dp` for the user's state+mode (`vehicle_data.core_ratings.modes.<B|E|C|F>` on garage cards), exactly one decimal; **null → "—" and no stars** — never "0.0" with a filled row.
- Hero `GET /api/my-garage/savings-summary/`: `max_potential_annual_savings` is **per-year cents** vs the garage's lowest-cost match at the same km/mode as the CV; render per year, no "save up to", name the baseline; refetch after every garage change.
- Hide the Category Avg. toggle for launch (Gio 3-Nov). Results modal: variant line wraps (no ellipsis). Tooltips: paste Dev-paste blocks 1–6 and 9 char-for-char; FB-01 fallback for any missing label; fix the Driveaway ⓘ key lookup (Flag 3) and the hard-coded QLD label (Flag 2). Favicon/manifest/JSON-LD per B-24. Match cards come only from live rows (never the CV; strip duplicated make in model string).
- `GET /api/vehicles/<id>/` shape note: vehicle fields are **top level**; `core_arcs` top level; `engine_data` is not present on this endpoint — band info is under `mode_data_by_state.<state>.<mode>.band_name`.

---

## Verification curls (no auth)

```bash
# Band name + arcs (expect: Everyday Legend™ / everyday-legend)
curl -s "https://api.carreb.com.au/api/vehicles/2f6beb87-aa31-4496-bb17-39cc58839ce9/?state=NSW" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); m=d['mode_data_by_state']['NSW']['B']; print(m['band_name'], '| arcs:', d['core_arcs']['modes']['B'])"

# Finder with relaxation
curl -s "https://api.carreb.com.au/api/vehicles/?budget_min=55000&budget_max=65000" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['count'], d.get('relaxation'))"

# Held vs live search
curl -s -X POST "https://api.carreb.com.au/api/my-garage/current-vehicle/search/" \
  -H "Content-Type: application/json" -d '{"query": "aston martin vanquish"}' | head -c 200; echo
curl -s -X POST "https://api.carreb.com.au/api/my-garage/current-vehicle/search/" \
  -H "Content-Type: application/json" -d '{"query": "zeekr 009 awd"}' | head -c 200; echo

# Image live
curl -s -o /dev/null -w "zeekr image: %{http_code} %{size_download}B\n" \
  https://api.carreb.com.au/media/vehicle_images/zeekr-009-2026.png
```

**QA anchors:** 2026 009 FWD, QLD, Pure Cost = **4.9**; Chery Tiggo 9 Elite FWD **3.6**; BYD Sealion 8 Dynamic FWD **4.5**; LC300 Sahara QLD = 2.5 / 3.9 / 4.2 / 4.2 across B/E/C/F.

---

*Backend contact: Ali. Anything here that doesn't match what the API returns is a backend bug — send the curl + response and I'll fix it.*
