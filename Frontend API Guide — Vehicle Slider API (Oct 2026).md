# Frontend API Guide — Vehicle Slider API (GET /api/vehicles/)

**Base URL:** `https://api.carreb.com.au`
**Auth:** none required — this endpoint is public.
**Verified against production on 29-Oct-2026.**

One GET endpoint feeds the vehicle slider/carousel. It reads from the
`vehicles` table only. All examples below are copy-paste curl commands with
the real response shape.

---

## 1. The slider endpoint

```
GET /api/vehicles/
```

Returns a paginated list of vehicles, newest catalogue data first. Every
vehicle object in `results` has the same shape (see §3).

### Query params (all optional — combine freely)

| Param | Type | Matches | Example |
|---|---|---|---|
| `page` | int | page number (default 1) | `2` |
| `page_size` | int | per page, default 20, **max 100** | `50` |
| `brand` | string | exact, case-insensitive | `Toyota` |
| `model` | string | exact, case-insensitive | `Kluger` |
| `year` | int | exact | `2026` |
| `powertrain_type` | string | exact, case-insensitive | `bev` `phev` `hybrid` `petrol` `diesel` |
| `body_style` | string | exact, case-insensitive | `suv` `sedan` `hatchback` `ute` `van` `wagon` |
| `num_seats_min` | int | seats ≥ value | `7` |
| `fcai_category` | string | exact, case-insensitive | `Large SUV` |
| `ancap_rating_min` | int | ANCAP stars ≥ value | `5` |

---

## 2. Curl commands & responses

### 2.1 Plain slider (no filters)

```bash
curl -sS "https://api.carreb.com.au/api/vehicles/?page=1&page_size=2"
```

**200:**
```json
{
  "count": 1726,
  "next": "https://api.carreb.com.au/api/vehicles/?page=2&page_size=2",
  "previous": null,
  "results": [
    {
      "id": "b9aea5d2-b1d6-41cf-9b6c-ac5531202f0c",
      "brand": "Alfa Romeo",
      "model": "Giulia",
      "year": 2025,
      "variant": "Sprint",
      "body_style": "sedan",
      "num_seats": 5,
      "powertrain_type": "petrol",
      "fcai_category": "Medium",
      "fcai_broad": "Passenger Cars",
      "ancap_safety_rating": null,
      "energy_norm": "petrol",
      "drive": "",
      "engine_l": null,
      "battery_kwh": 0.0,
      "is_scoring_outlier": false,
      "scoring_version": "v6.4-rebatch-07Oct26 (assumptions 25-Sep-26; national ratings; C/F value lost)",
      "image_url": "/media/vehicle_images/alfa-romeo-giulia-2026.png",
      "research_status": "v6.3.4 seed",
      "energy_type": "Combustion",
      "cost_category": "Medium",
      "au_launch": "n/a (v6.3.4 seed vehicle)",
      "co2_energy_cycle_g_per_km": 237.8,
      "spotlight_data": {
        "count": 0,
        "badges": "",
        "version": "v6.4-derived-percentile (Mode B, category-aware)",
        "green_lean": false,
        "range_kings": false,
        "core_allstars": false,
        "unicorn_match": false,
        "category_sweep": false
      }
    }
  ]
}
```

- `count` — total vehicles matching the filters (use it for "Showing X cars").
- `next` / `previous` — fully-built URLs for the next/prev page; `null` at the ends.
  For an infinite slider, just keep fetching `next` until it's `null`.
- `page_size` max is 100; asking for more returns 100.

### 2.2 Filtered slider (brand + body style + 7 seats)

```bash
curl -sS "https://api.carreb.com.au/api/vehicles/?brand=Toyota&body_style=suv&num_seats_min=7&page_size=2"
```

**200:**
```json
{
  "count": 9,
  "next": "https://api.carreb.com.au/api/vehicles/?body_style=suv&brand=Toyota&num_seats_min=7&page=2&page_size=2",
  "previous": null,
  "results": [
    {
      "id": "52699bf0-0cd1-49a3-91b6-a251494f4265",
      "brand": "Toyota",
      "model": "Kluger",
      "year": 2026,
      "variant": "Grande",
      "body_style": "suv",
      "num_seats": 7,
      "powertrain_type": "hybrid",
      "fcai_category": "Large SUV",
      "fcai_broad": "SUVs",
      "ancap_safety_rating": null,
      "energy_norm": "hev",
      "drive": "AWD",
      "engine_l": 2.5,
      "battery_kwh": 0.0,
      "is_scoring_outlier": false,
      "scoring_version": "v6.4-audit-27Oct26",
      "image_url": "/media/vehicle_images/toyota-kluger-2026.png",
      "research_status": "Confirmed",
      "energy_type": "Combustion",
      "cost_category": "Large SUV",
      "au_launch": "current (in market FY26)",
      "co2_energy_cycle_g_per_km": 162.4,
      "spotlight_data": {
        "count": 0,
        "badges": "",
        "version": "v6.4-spotlight-rules-v2 (27-Oct-26)",
        "green_lean": false,
        "range_kings": false,
        "core_allstars": false,
        "unicorn_match": false,
        "category_sweep": false
      }
    }
  ]
}
```

### 2.3 EV-only slider

```bash
curl -sS "https://api.carreb.com.au/api/vehicles/?powertrain_type=bev&page_size=20"
```

Same response shape; `count` is the number of BEVs.

### 2.4 Single vehicle (slider card tap → detail)

```bash
curl -sS "https://api.carreb.com.au/api/vehicles/52699bf0-0cd1-49a3-91b6-a251494f4265/"
```

**200:** one flat object — **all** columns of the vehicle (not just the list
fields), same values as above plus the full detail set (all cost fields,
driveaway-by-state, scoring fields, etc.). 404 `{"detail": "Not found."}` for
an unknown id.

---

## 3. Field reference for one vehicle (slider card)

| Field | Type | Notes for the UI |
|---|---|---|
| `id` | UUID | use in the detail URL and garage add calls |
| `brand` `model` `variant` `year` | string/int | card title, e.g. "2026 Toyota Kluger Grande" |
| `body_style` | string | `suv` `sedan` `hatchback` `ute` `van` `wagon`… |
| `num_seats` | int | |
| `powertrain_type` | string | `bev` `phev` `hybrid` `petrol` `diesel` `fcev` |
| `fcai_category` | string | size class, e.g. `Large SUV` |
| `fcai_broad` | string | `Passenger Cars` / `SUVs` / `Light Commercial` / `Heavy Commercial` |
| `ancap_safety_rating` | int \| null | null = unknown, show nothing |
| `drive` | string | `FWD` `RWD` `AWD` `4x4`, may be `""` |
| `engine_l` | float \| null | litres; null for EVs |
| `battery_kwh` | float | 0.0 for combustion |
| `image_url` | string \| null | relative path — prefix with the base URL; **null → show placeholder tile** |
| `co2_energy_cycle_g_per_km` | float \| null | tailpipe CO₂ |
| `cost_category` | string | category used for costing |
| `au_launch` | string | market status text |
| `research_status` | string | `Confirmed` = fully researched |
| `energy_type` | string | `Combustion` / `Electric` |
| `is_scoring_outlier` | bool | scoring caveat flag |
| `scoring_version` | string | data provenance stamp |
| `spotlight_data` | object | badge chips, see §4 |

## 4. Spotlight badges (`spotlight_data`)

```json
{
  "count": 3,
  "badges": "Range Kings™, Category Sweep™, CORE All-Stars™",
  "version": "v6.4-spotlight-rules-v2 (27-Oct-26)",
  "green_lean": true,
  "range_kings": true,
  "core_allstars": true,
  "unicorn_match": false,
  "category_sweep": true
}
```

- One boolean per badge — **render a chip only when its boolean is `true`**.
  Don't parse the `badges` string for logic; it's display copy.
- `count` = how many badges the car holds (0–5). No car currently holds 5.
- Badge labels: `Green & Lean™` `Range Kings™` `CORE All-Stars™`
  `Unicorn Match™` `Category Sweep™`.

## 5. Dropdown helpers (feed the slider's filter UI)

All public GET, same base URL, read from the same table:

```bash
# makes
curl -sS "https://api.carreb.com.au/api/vehicles/brands/"
# → ["Alfa Romeo","Alpina",...]

# models for a make
curl -sS "https://api.carreb.com.au/api/vehicles/models/?brand=Toyota"
# → ["Camry","Corolla","Kluger",...]

# years for a make+model
curl -sS "https://api.carreb.com.au/api/vehicles/years/?brand=Toyota&model=Kluger"
# → [2027, 2026, 2025,...]

# variants for a make+model+year
curl -sS "https://api.carreb.com.au/api/vehicles/variants/?brand=Toyota&model=Kluger&year=2026"
# → ["GX","GXL","Grande",...]
```

- All four return a plain JSON array of strings/ints.
- Missing required params → `400 {"detail": "brand is required"}` (wording names
  the missing param).

---

## 6. Checklist

- [ ] Build image URLs as `<base_url><image_url>`; handle `null` with a placeholder.
- [ ] Use `next` for infinite scroll; stop when `null`.
- [ ] Keep `page_size` ≤ 100.
- [ ] Filter values are case-insensitive exact matches — populate them from the
      §5 dropdown helpers, never free-typed.
- [ ] Spotlight chips from booleans, not the `badges` string.
