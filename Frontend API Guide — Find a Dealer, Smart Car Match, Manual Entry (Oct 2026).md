# Frontend API Guide — Find a Dealer · AI Smart Match · Manual Entry

**Base URL:** `https://api.carreb.com.au`
**Auth:** all endpoints except where noted require `Authorization: Bearer <access_token>`
(login: `POST /api/users/login/` with `{"email", "password"}` → `access` token)

---

## 1. Find a Dealer

Two shapes of the same endpoint. The **GET route is the spec-canonical one** — use it for new work. The POST route exists for backward compatibility.

### 1.1 Search — `GET /api/garage/find-a-dealer/`

Query params:

| Param | Required | Notes |
|---|---|---|
| `postcode` | yes | 4-digit Australian postcode (200–299, 800–899, 1000–9999) |
| `radius` | yes | one of `5`, `25`, `50`, `100` (km) |
| `brand` | one of brand / garage_vehicle_id | e.g. `Toyota` |
| `garage_vehicle_id` | one of brand / garage_vehicle_id | UUID from `GET /api/my-garage/vehicles/` |

Example: `GET /api/garage/find-a-dealer/?postcode=2000&radius=25&brand=Toyota`

**Success — 200:**
```json
{
  "vehicle_brand": "Toyota",
  "search_postcode": "2000",
  "search_radius_km": 25,
  "results": [
    {
      "dealer_name": "Sydney City Toyota",
      "distance_km": 2.7,
      "phone": "(02) 9565 6313",
      "website_url": "http://www.sydneycitytoyota.com.au/",
      "maps_url": "https://maps.google.com/?cid=...",
      "link_url": "http://www.sydneycitytoyota.com.au/",
      "place_ref": "https://maps.google.com/?cid=...",
      "rating": 4.4,
      "external_link_notice": "You will leave Carreb and the dealer's own terms and privacy policy will apply."
    }
  ],
  "brand_locator_fallback_url": "https://www.toyota.com.au/find-dealer",
  "disclaimer": "Dealer information sourced from public listings. Carreb is independent — we don't earn commissions from dealers or manufacturers."
}
```

- Up to **5 results**, sorted by `distance_km` ascending.
- `link_url` = the dealer's own website when Google has one, otherwise their Maps listing. **Point the "Visit Website" button at `link_url`.**
- `maps_url` is always the Google Maps listing (use for a secondary "Directions" link if wanted).
- Render `phone`, `distance_km` (e.g. "3.4 km"), and `rating` (may be `null`).
- Always render `disclaimer` in the modal footer.

**Genuinely no dealers — 200:**
```json
{
  "vehicle_brand": "Toyota",
  "search_postcode": "2000",
  "search_radius_km": 5,
  "results": [],
  "no_results_message": "No Toyota dealers found within 5km of the 2000 area. Try expanding your search radius.",
  "brand_locator_fallback_url": "https://www.toyota.com.au/find-dealer",
  "disclaimer": "..."
}
```
Show `no_results_message` and a link to `brand_locator_fallback_url` (official brand locator or Google search fallback).

**Upstream outage — 200 (distinguish this from "no dealers"):**
```json
{
  "results": [],
  "service_unavailable": true,
  "message": "Dealer search is temporarily unavailable. Please try again shortly.",
  "disclaimer": "..."
}
```
Show `message` as an info/warning state — do **not** show the "expand your radius" UI here.

**Validation errors — 422:**
```json
{"error": "invalid_postcode", "message": "Please enter a valid 4-digit Australian postcode."}
{"error": "invalid_radius", "message": "Radius must be 5, 25, 50, or 100 km."}
```

### 1.2 (Legacy) Search — `POST /api/my-garage/find-dealer/`

```json
{"garage_vehicle_id": "<uuid>", "postcode": "2000", "radius_km": 25}
```
Same response bodies as above; `vehicle_brand` is derived from the garage vehicle. Rate-limited to 100/day/user.

### 1.3 Outbound click analytics — `POST /api/analytics/dealer-link-clicked/`

Fire when the user clicks a dealer link:
```json
{
  "vehicle_brand": "Toyota",
  "dealer_name": "Sydney City Toyota",
  "vehicle_id": "<vehicle uuid, optional>",
  "link_url": "http://www.sydneycitytoyota.com.au/"
}
```
`vehicle_id` and `link_url` are optional but should be sent. Returns `200` empty.

### Modal UX flow
1. User opens "Find a dealer" on a vehicle → modal title "Find a {Make} dealer near you".
2. Inputs: postcode + radius selector (5 / 25 / 50 / 100 km).
3. Call the GET endpoint → render results list (name, distance, phone, Visit Website → `link_url`).
4. Show `disclaimer` in footer at all times.
5. On click: fire §1.3 analytics, then open `link_url` in a new tab.

---

## 2. AI Smart Match (Smart Car Match)

`POST /api/my-garage/ai-smart-match/`
Paid plans only (`IsPaidMember`).

**Request:**
```json
{"query": "7 seater SUV under 70k with 5 star safety", "state": "NSW"}
```
- `query` (required, ≤500 chars): free text.
- `state` (optional): one of NSW/VIC/QLD/SA/WA/NT/TAS/ACT. Falls back to the user's current-vehicle state, then NSW.

**Success — 200:**
```json
{
  "results": [
    {
      "vehicle_id": "b9aea5d2-...",
      "make": "Toyota",
      "model": "Kluger",
      "year": 2025,
      "variant": "GXL",
      "powertrain_type": "petrol",
      "core_rating": 4.2,
      "band_name": "Excellent",
      "total_annual_cost": 18450,
      "total_annual_cost_display": "$18,450",
      "est_cost_difference": 1200,
      "est_cost_difference_display": "$12 less",
      "co2_g_per_km": 180.5,
      "driveaway_price": 6500000,
      "driveaway_price_display": "$65,000",
      "recommendation_reason": "Matches your 7-seat requirement...",
      "is_estimate": true,
      "model_group": "Toyota Kluger 2025"
    }
  ],
  "match_count_used": 3,
  "match_count_limit": 10,
  "ai_service_available": true,
  "interpreted_filters": {"num_seats_min": 7, "budget_max": 70000, "ancap_rating_min": 5, "body_styles": ["suv"]},
  "relaxed_filters": [],
  "meta": {
    "calculated_at": "...",
    "is_estimate": true,
    "disclaimer": "All figures are estimates only. Actual costs will vary based on individual driving habits, insurer quotes, dealer pricing, and personal circumstances."
  }
}
```

**Behaviour guarantees (frontend can rely on these):**
- **At least 5 results** whenever enough vehicles exist in the catalogue. Over-strict filters are relaxed automatically; anything relaxed is listed in `relaxed_filters` (e.g. `["ancap_rating_min", "budget_max"]`) — optionally surface "We relaxed: budget" as a chip.
- **One variant per model**: each model line appears exactly once. The representative is the **cheapest variant** — unless a better-rated trim is within **+10%** of the cheapest price, in which case that smarter-buy trim wins. A variant with no price never beats a priced one.
- **Named-car boost**: if the user names a make/model (e.g. "Mazda CX-5"), that car's results appear first and its `recommendation_reason` is prefixed with `"Your searched car — Mazda CX-5. ..."`.
- Results are ordered by name match → CORE rating → cost. Never alphabetical.
- `est_cost_difference` is cents vs the user's current vehicle (positive = cheaper). Display `*_display` strings directly.
- `total_annual_cost` is in **cents** — always use `total_annual_cost_display` / `driveaway_price_display` for rendering.
- `core_rating` / `band_name` may be `null` if a vehicle can't be rated.
- Always render `meta.disclaimer`.

**AI unavailable — 200:**
```json
{"results": [], "ai_service_available": false, "fallback_message": "AI matching is temporarily unavailable. Please use Smart Car Finder to find your vehicle."}
```

**Nothing matched — 200:**
```json
{"results": [], "ai_service_available": true, "interpreted_filters": {...}, "relaxed_filters": [...], "empty_message": "No vehicles matched your search. Try broadening your criteria or use Smart Car Finder.", "match_count_used": 3, "match_count_limit": 10}
```

**Plan limit — 403:**
```json
{"error": "match_limit_reached", "match_count_used": 10, "match_count_limit": 10, "plan": "Free Starter", "upgrade_message": "Upgrade to CORE Advantage for unlimited matches."}
```
Show an upgrade prompt.

---

## 3. Vehicle Lookup & Manual Entry (Current Vehicle)

### 3.1 Search — `POST /api/my-garage/current-vehicle/search/`

Public (no auth required). Free-text search across the Carreb catalogue (new cars) + GVG records (older cars).

**Request:** `{"query": "2018 mazda cx-5 maxx"}`
A 4-digit token in the query is treated as the year filter; remaining words match make/model/variant.

**Response — 200:** array of up to 10 results, newest first, catalogue preferred:
```json
[
  {
    "id": "cc9f67d0-...",
    "source": "carreb",
    "year": 2025,
    "make": "Mazda",
    "model": "CX-5",
    "variant": "Maxx",
    "body_style": "suv",
    "powertrain_type": "petrol",
    "fuel_consumption_per_100km": 7.4,
    "electricity_consumption_per_100km": null,
    "tailpipe_co2_g_per_km": 172.0,
    "image_url": "/media/vehicle_images/....jpg",
    "name": "Mazda CX-5 Maxx"
  },
  {
    "id": "a1b2c3d4-...",
    "source": "gvg",
    "year": 2018,
    "make": "Mazda",
    ...
    "name": "2018 Mazda CX-5 Maxx Sport"
  }
]
```
- `source` is `"carreb"` (catalogue) or `"gvg"` (older dataset). Same shape either way.
- Empty query or no matches → `[]`.

### 3.2 Cascade dropdowns — `GET /api/current-vehicle/makes|models|years/`

Auth required. Each returns `{"results": [{"value", "label"}, ...]}` and always appends an **"Other / not listed"** option.

| Endpoint | Params | Notes |
|---|---|---|
| `/api/current-vehicle/makes/` | — | All makes across catalogue + GVG |
| `/api/current-vehicle/models/` | `make` | Models for that make |
| `/api/current-vehicle/years/` | `make`, `model` | Years for that make+model, newest first |

If the user picks **"Other / not listed"** (or search finds nothing), offer the **AI search** button (§3.3).

### 3.3 AI vehicle search — `POST /api/current-vehicle/ai-search/`  ⭐ new

Explicit user action only — call it when the user clicks "Search with AI", **not** on every keystroke. Grok is billed per distinct query; repeats are server-cached.

**Request:** `{"query": "1996 Toyota Soarer GT-T"}` (min 3 chars)

**Success — 200:**
```json
{
  "results": [
    {
      "id": "8f4e...",
      "source": "ai",
      "name": "1996 Toyota Soarer GT-T",
      "make": "Toyota",
      "model": "Soarer",
      "year": 1996,
      "variant": "GT-T",
      "body_style": "coupe",
      "powertrain_type": "petrol",
      "engine_l": 2.5,
      "battery_kwh": null,
      "num_seats": 4,
      "ancap_safety_rating": null,
      "fuel_consumption_combined_l_100km": 9.8,
      "electricity_consumption_wh_per_km": null,
      "electric_range_km": null,
      "tailpipe_co2_g_per_km": 228.0,
      "fcai_category": "Sports",
      "driveaway_price_estimate": 2500000,
      "driveaway_price_display": "$25,000",
      "search_count": 4,
      "selected_count": 0
    }
  ],
  "from_cache": true,
  "ai_available": true
}
```
`from_cache: true` means Grok wasn't re-billed. Many spec fields may be `null` (AI estimate, not lab data) — the UI should show "AI estimate" badges for these and let the user edit values later via overrides.

**AI down — 502:** `{"detail": "...", "ai_available": false, "results": []}` — show a "try again later" state.

### 3.4 Saving the selection — `POST /api/my-garage/current-vehicle/`

**One of** the four ID fields identifies the vehicle:

```json
{
  "vehicle_catalogue_id": "<uuid>",        // from §3.1 source=carreb (or search)
  "green_vehicle_guide_record_id": "<uuid>", // from §3.1 source=gvg
  "ai_vehicle_entry_id": "<uuid>",           // from §3.3  ⭐ new
  "manual_entry_data": {...},                // legacy free-form fallback
  "purchase_date": "2019-04-12",
  "licence_plate": "ABC123",
  "odometer_reading": 82000,
  "state": "NSW"
}
```
All fields optional. Passing `ai_vehicle_entry_id` stores a **full spec snapshot** (emissions, consumption, seats, category, price estimate) on the current vehicle, so cost calculations and CO₂ figures work — this is the fix for the "manual entry vehicles missing data" problem. Selecting an AI entry bumps its `selected_count` server-side.

Side effects: if a `vehicle_catalogue_id` is saved that isn't in the user's garage yet, a garage vehicle is auto-created (subject to plan cap → `403` with `cap_counter`).

**Response — 200:** the calculated current-vehicle object (same shape as `GET /api/my-garage/current-vehicle/`). `GET` returns `null` when no current vehicle is set.

### Manual entry flow (end-to-end)
1. User types in lookup → `POST /api/my-garage/current-vehicle/search/`.
2. If results → user picks one → `POST /api/my-garage/current-vehicle/` with the matching ID field.
3. If no results (or user picks "Other / not listed") → show **"Search with AI"** button → `POST /api/current-vehicle/ai-search/`.
4. User picks an AI result → `POST /api/my-garage/current-vehicle/` with `ai_vehicle_entry_id`.
5. If AI also fails → free-form manual entry (`manual_entry_data`) as last resort.

---

## 4. Calculator Lookup — Finance Section

`GET /api/vehicles/lookup/?name=<vehicle_name>&state=<state>` (public)

The `finance` block now carries the **full finance field set**, each defaulted from the server's FinanceDefaults table (per broad vehicle category):

```json
"finance": {
  "deposit_pct": 10.0,
  "deposit_amount": 4149.0,
  "loan_amount": 37341.0,
  "loan_term_months": 60,
  "interest_rate_pct": 8.78,
  "balloon_pct": 0.0,
  "balloon_amount": 0.0,
  "monthly_repayment": 771.16,
  "monthly_repayment_display": "$771",
  "finance_cost_pa": 1985.68,
  "finance_cost_pa_display": "$1,986",
  "estab_fee": 400.0,
  "admin_fee_monthly": 10.0
}
```

Field semantics:

| Field | Editable | Notes |
|---|---|---|
| `deposit_pct` | ✅ | Default from FinanceDefaults (typically 10% of driveaway). Changing it recalculates `deposit_amount` and `loan_amount`. |
| `loan_amount` | ✅ | Calculated as driveaway − deposit. Default from FinanceDefaults chain. |
| `loan_term_months` | ✅ | Default from FinanceDefaults (typically 60). |
| `interest_rate_pct` | ✅ | FinanceDefaults base rate, **already including the alt-fuel modifier** (−0.5 pp for BEV/PHEV). |
| `balloon_pct` | ✅ | Default from FinanceDefaults (typically 0). |
| `monthly_repayment` / `monthly_repayment_display` | ❌ read-only | Calculated P&I — same visual treatment as the Depreciation (%) CALCULATION chip. Never a typed value. |
| `finance_cost_pa` / `finance_cost_pa_display` | ❌ read-only | **Yearly interest + fees** — this feeds the "Finance – $X" section header. |
| `estab_fee`, `admin_fee_monthly` | ❌ | Shown for transparency; included in `finance_cost_pa`. |

Clear/Default chips: reset each field to the value in this response.

**Sending edits back:** pass the user's values in `user_inputs` when calling `POST /api/core-rating/calculate/` (and batch/search) so COOL Choice and Full Picture recalculate with them:
```json
"user_inputs": {
  "deposit_pct": 15.0,
  "loan_term_months": 48,
  "interest_rate": 8.5,
  "balloon_pct": 20.0
}
```
`loan_amount` can also be sent explicitly (overrides the driveaway−deposit calculation). Precedence when a value is omitted: `user_inputs` → FinanceDefaults for the vehicle's category.

---

## Changelog (this release)

| Area | Change |
|---|---|
| Find a Dealer | New spec route `GET /api/garage/find-a-dealer/` (brand or garage_vehicle_id); results now include `phone`, `website_url`, `maps_url`, `link_url`, `rating`; outage now returns `service_unavailable: true` instead of a fake "no dealers found" |
| Dealer analytics | `POST /api/analytics/dealer-link-clicked/` accepts `dealer_name`, `vehicle_id`, `link_url` |
| AI Smart Match | Minimum 5 results via auto-relaxation (`relaxed_filters`); **one variant per model — cheapest wins**; named-car boost with "Your searched car" reason; rating→cost ordering (never alphabetical) |
| Smart Car Finder (`/api/core-rating/search/`) | Deduplication changed: one vehicle per (brand, model) — cheapest variant for the state replaces cheapest-by-COO per (brand, model, year); better-rated trim within +10% of cheapest price wins |
| Finance section | `lookup` finance block expanded: `deposit_pct`, `deposit_amount`, `interest_rate_pct` (incl. alt-fuel modifier), `balloon_pct`, `balloon_amount`, `monthly_repayment` (+display, read-only calculated), `finance_cost_pa` (+display, yearly interest + fees for the "Finance – $X" header), `estab_fee`, `admin_fee_monthly`. Rating-engine fallback (Modes E/F when no stored workbook value) now uses FinanceDefaults instead of hardcoded 80%/7.5%/60, honours `deposit_pct`/`balloon_pct` user inputs, and counts interest + fees (not principal) as the annual finance cost |
| Manual Entry | New `POST /api/current-vehicle/ai-search/` (Grok, cache-per-query) and `ai_vehicle_entry_id` on save; cascade dropdowns include "Other / not listed" |
