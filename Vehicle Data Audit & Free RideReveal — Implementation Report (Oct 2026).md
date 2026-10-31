# Vehicle Data Completeness, Storage & Free RideReveal — Implementation Report

Date: 31-Oct-2026 · Backend commit: (see `git log`) · Scope: GVG, Carreb catalogue, AI Search Vehicles, Vehicle Lookup, Smart Car Finder (Free Match), AI Smart Match, My Garage, Current Vehicles, RideReveal.

---

## 1. Root causes identified

1. **Five+ hand-rolled response shapes.** Every search surface built its own ad-hoc dict of vehicle fields, so "missing fields" depended on which endpoint you hit. The current-vehicle search returned 10 fields, the garage card ~12, AI Smart Match ~18, Free Match ~15, the public list API ~20. No surface carried the full column set.
2. **No fallback hierarchy.** A field that was null in the DB was simply emitted as null. Nothing filled it from the sheet defaults (CategoryCostDefault, Insurance/CTP/Rego benchmarks, maintenance/tyre tables), and nothing used AI estimation at serve time.
3. **The 2025 Hilux "missing Driveway Price" case.** The catalogue only carries MY2026 (that's what the final-launch workbook contains — verified on the server: 15 Hilux rows, all 2026, all priced). A "2025 Hilux" query therefore falls through to the AI search, and Grok returns no driveaway price → null. Now covered by the defaults tier: nearest catalogue year price for the same make+model, flagged `"default"` in `field_sources`.
4. **Duplicate garage rows.** `POST /api/my-garage/vehicles/` always created a new row; re-adding (or adding from two different flows) produced duplicates. Free-match save had the same gap.
5. **RideReveal credits consumed but never refunded on failure** (the job view even claimed `credit_refunded: true` while no refund happened), and free-tier users had no sign-up entitlement at all.

## 2. The fix: one canonical vehicle card

New service: `apps/vehicles/services/vehicle_card.py` — `build_vehicle_card(record, source, state)`.

- **Complete schema.** Every response now carries the full unified field set (`CARD_FIELDS`): identity (make/model/year/variant/body/powertrain/fuel/drive/transmission/seats/doors/ANCAP/tow/ranges/consumption/CO2/FCAI category), media (`image_url`, `spotlight_data`), and all pricing/cost columns (`driveaway_price` + per-state, servicing 5yr, tyres, resale 5yr, CTP/insurance/registration per state, 5yr ownership totals). Fields are never omitted for being null.
- **Provenance per field.** `field_sources` maps every field to `"db"` (actual database value), `"default"` (sheet-derived assumption, e.g. category cost defaults, nearest-year twin price), `"ai"` (Grok estimate or AI-search value), or is absent when genuinely unknown. Estimates are never presented as verified facts.
- **Fallback order implemented exactly as specified:** database value → sheet assumptions/defaults → AI estimation (cached 30 days per make/model/year for spec estimators).

## 3. Where every surface gets its data now

| Surface | Endpoint | Card applied |
|---|---|---|
| Vehicle Lookup search | `POST /api/my-garage/current-vehicle/search/` | ✅ carreb/gvg/ai rows all full card |
| AI Search Vehicles | `POST /api/current-vehicle/ai-search/` | ✅ full card + search/selected counts |
| My Garage list & detail | `GET /api/my-garage/vehicles/…` | ✅ merged into `vehicle_data` |
| Current Vehicle | `GET/POST /api/my-garage/current-vehicle/` | ✅ merged into `vehicle_data` |
| AI Smart Match | `POST /api/my-garage/ai-smart-match/` | ✅ result rows filled to card schema |
| Smart Car Finder (Free Match) | `POST /api/free-match/calculate/` + `…/save/` | ✅ both gated and unlocked responses |
| Public vehicle API | `GET /api/vehicles/` + detail | ✅ list serializer now includes all pricing/cost columns |

Existing response keys are preserved (backward compatible); the card fills the gaps.

## 4. Vehicle storage — where selected vehicles live

| Search method | Stored in | Table |
|---|---|---|
| Vehicle Lookup (carreb/gvg/ai) | `GarageVehicle` row + `CurrentVehicle` on select | `mygarage_garagevehicle`, `mygarage_currentvehicle` |
| AI Search Vehicles | same — `ai_vehicle_entry_id` FK (auto-created garage row on current-vehicle select; addable via garage POST) | + `vehicles_aivehicleentry` (spec cache) |
| Smart Car Finder (Free Match) | session row (`FreeMatchSession`), converted to `GarageVehicle` on save | `freematch_freematchsession` |
| AI Smart Match | selection saved via garage add (carreb rows) | `mygarage_garagevehicle` |

All storage is relational and persistent (survives logout/login/devices). Garage rows hold one FK per source: `vehicle_catalogue_id` (carreb) / `green_vehicle_guide_record_id` (GVG) / `ai_vehicle_entry_id` (AI), plus `source` (how it was added) and `status`.

**New behaviours:**
- First garage add automatically becomes the Current Vehicle (existing, retained).
- **Duplicate prevention:** re-adding an existing vehicle (any source, via garage POST or free-match save) returns the existing active row with `already_in_garage: true` instead of creating a second record. Free users still hit the plan cap only for genuinely new vehicles.
- Garage POST auto-routing retained: an id sent in the "wrong" field (`vehicle_catalogue_id` holding a GVG/AI id) is moved to the right FK automatically.

## 5. Free RideReveal entitlement

- `RideRevealCredit.free_reveal_used` (new column, migration `0014`) persists the one-off entitlement — tied to the user row, immune to logout/device changes, never reset by plan syncs.
- `POST /api/my-garage/ridereveal/generate/`: free-tier user with the entitlement unused consumes it (`credit_type: "free_signup"`) inside the existing `select_for_update` transaction — concurrent double-spends are impossible. Paid/plan credits are preferred when present, so buying a credit never burns the free one. Paid tiers unchanged.
- **Consumed only on success:** the generation task now refunds correctly on failure — free entitlement flag cleared, or `credits_used` decremented for paid credits. (The old refund was unconditional and wrong for the free path.)
- `GET /api/my-garage/ridereveal/credits/` now returns `free_reveal_available` and `free_reveal_used` so the frontend can gate the entry point.

## 6. Endpoints modified

- `POST /api/my-garage/vehicles/` — dedupe, auto current-vehicle, auto-routing (earlier commits)
- `GET/POST /api/my-garage/current-vehicle/` — full card in `vehicle_data`
- `POST /api/my-garage/current-vehicle/search/` — full cards for carreb/gvg/ai
- `POST /api/current-vehicle/ai-search/` — full cards
- `POST /api/my-garage/ai-smart-match/` — full card result rows
- `POST /api/free-match/calculate/`, `POST /api/free-match/{token}/save/` — full card responses, dedupe on save
- `GET /api/vehicles/`, vehicle detail — cost/pricing columns added
- `POST /api/my-garage/ridereveal/generate/`, `GET …/credits/` — free entitlement
- RideReveal generation task — credit-type-aware refund

Frontend changes required: **none are breaking**. Recommended: render `field_sources` badges ("Est." / "AI est.") next to fields whose source is not `db`, and use `free_reveal_available` to show/hide the free RideReveal entry point.

## 7. Test results

- New: `apps/vehicles/tests/test_vehicle_card.py` — complete schema for all 3 sources, db/default/ai provenance, nearest-year price fallback (the Hilux scenario), sheet-default cost fill, AI spec estimation.
- New: `GarageAddDedupeTests`, `FreeRideRevealEntitlementTests` — dedupe returns existing row; free reveal advertised → consumed once → paywall after; paid flow unaffected; failure refunds the entitlement.
- Full suite: **see commit message for the final count** (mygarage + freematch + vehicles all green).

## 8. Acceptance criteria check

1. Consistent complete structure across search methods — ✅ card service.
2. All DB columns mapped — ✅ `CARD_FIELDS` superset; public serializer extended.
3. db → defaults → AI hierarchy — ✅ with per-field provenance.
4. Driveway price populated wherever possible — ✅ incl. nearest-year twin fallback.
5. AI Search Vehicles same rules — ✅.
6. Selection auto-saves to My Garage — ✅ (garage add, current-vehicle select, free-match save; all deduped).
7. Current Vehicles saved & associated — ✅.
8. Persistence across sessions/devices — ✅ relational storage.
9. Duplicates prevented — ✅.
10. Free users get exactly one free RideReveal — ✅.
11. No API bypass — ✅ row-locked consumption, server-side entitlement.
12. Failed reveals don't consume — ✅ type-aware refund.
13. Paid users unaffected — ✅ covered by tests.
