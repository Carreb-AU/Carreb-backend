# Frontend API Guide — GVG & AI Vehicle Details via the Vehicle API (2-Nov-2026)

**Base URL:** `https://api.carreb.com.au`
**Verified against production on 2-Nov-2026.**
**Frontend changes required: NONE.** This is the fix for "GVG/AI vehicles in
My Garage / Current Vehicle show no details on their cards".

---

## What was wrong

When you open a garage or current-vehicle card, the app fetches the car's
details with `GET /api/vehicles/<id>/`, using whichever id the garage row
carries (`vehicleCatalogueId || greenVehicleGuideRecordId || aiVehicleEntryId`).

That endpoint only knew about the new-car catalogue. GVG (used/older car)
ids and AI-search ids returned **404**, so the enrichment step silently did
nothing and the card rendered with only the sparse garage-row data — no
image, no running costs, no CO₂, no resale, no specs.

## What changed

`GET /api/vehicles/<id>/` is now polymorphic. It resolves in this order:

1. **Carreb catalogue** (`Vehicle`) → unchanged response, same as before.
2. **GVG** (`VehicleIdentity`) → new: returns a full catalogue-shaped payload.
3. **AI search** (`AIVehicleEntry`) → new: same full payload.
4. Nothing matches → 404.

The GVG/AI payload carries **every key the frontend mappers already read**
(`brand`, `seats`, `annual_km_default`, `ancap_rating`, `drive_type`,
`fuel_consumption_l_100km`, `battery_capacity_kwh`, `engine_data`, …), so
the existing enrichment code (`enrichCurrentVehicleFromCatalogue`,
`enrichGarageVehicleFromCatalogue`) starts working for GVG/AI cars with
**no code changes on your side**. The "Est. Annual Running Costs", "Est.
CO₂", "Estimated km p.a.", "Est. fuel range" and "Resale value (est.)" rows
now populate for GVG and AI cars exactly like catalogue cars.

Responses are cached 15 minutes server-side (per id + state); the endpoint
stays public (`AllowAny`), same as before.

---

## Request

```bash
GET /api/vehicles/<vehicle_id>/
```

- No auth required (public, unchanged).
- Optional query param: `?state=NSW` (any AU state) — picks the default
  driveaway price for state-dependent fields. Defaults to NSW.

The id can be any of the three ids — the endpoint sorts out which table it
belongs to. You keep calling it exactly the way you do today.

---

## Response shapes

### a) Carreb catalogue id — unchanged

Same `VehicleDetailSerializer` output as always (all model columns).
Nothing to do.

### b) GVG id — `200 OK`, `source: "gvg"`

Live example: `GET /api/vehicles/ebeb0db5-fab2-4908-8d9a-758e2d819837/`
(2015 Toyota Corolla, GVG):

```json
{
  "id": "ebeb0db5-fab2-4908-8d9a-758e2d819837",
  "source": "gvg",
  "name": "2015 Toyota Corolla",
  "make": "Toyota",
  "brand": "Toyota",
  "model": "Corolla",
  "year": 2015,
  "variant": "Ascent",
  "body_style": "hatchback",
  "powertrain_type": "petrol",
  "fuel_type": "petrol",
  "fuel_type_raw": "Petrol 91RON",
  "drive": "FWD",
  "drive_type": "FWD",
  "drivetrain": "FWD",
  "transmission": "CVT",
  "num_seats": 5,
  "seats": 5,
  "doors": 5,
  "engine_l": 1.8,
  "battery_kwh": 0.0,
  "battery_capacity_kwh": null,
  "ancap_safety_rating": 5,
  "ancap_rating": 5,
  "tow_braked_kg": 1300,
  "tow_unbraked_kg": 600,
  "test_cycle": "ADR",
  "fcai_category": "Light",
  "fcai_broad": "Passenger Cars",
  "fuel_consumption_combined_l_100km": 6.1,
  "fuel_consumption_l_100km": 6.1,
  "combined_fuel_consumption_l_100km": 6.1,
  "tailpipe_co2_g_per_km": 143.0,
  "wltp_range_km": null,
  "electric_range_km": 0.0,
  "fuel_range_km": 902,
  "range_petrol_km": 902,
  "range_total_km": 902,
  "annual_km": 11000,
  "annual_km_default": 11000,
  "image_url": "/media/vehicle_silhouettes/light-category-hatch.png",
  "spotlight_data": null,
  "driveaway_price": 3700000,
  "driveaway_price_by_state": null,
  "resale_value_5yr_estimate": 185000,
  "resale_value_5yr": 185000,
  "resale_value": 185000,
  "resale_percent": 5.0,
  "field_sources": {
    "make": "db", "model": "db", "year": "db", "variant": "db",
    "fuel_consumption_combined_l_100km": "db",
    "tailpipe_co2_g_per_km": "db",
    "driveaway_price": "default",
    "resale_value_5yr_estimate": "default"
  },
  "engine_data": {
    "core_rating": null,
    "band_name": "",
    "band_slug": "",
    "total_annual_cost": 444410,
    "annual_cost_breakdown": {
      "fuel": 90000, "electricity": 0, "ctp": 50000,
      "comprehensive": 150000, "registration": 40000,
      "servicing": 40000, "tyres": 20000, "road_user_charge": 0,
      "fuel_or_energy_annual": 90000, "insurance_annual": 150000,
      "ctp_annual": 50000, "registration_annual": 40000,
      "servicing_annual": 40000, "tyres_annual": 20000,
      "ev_levy_annual": 0, "total_annual": 444410
    },
    "tailpipe_co2_g_per_km": 143.0,
    "annual_co2_kg": 1573,
    "annual_km": 11000,
    "is_estimate": true,
    "resale_value_5yr_estimate": null
  }
}
```

(Exact numbers vary per car; the **key set** is what to code against.)

### c) AI-search id — `200 OK`, `source: "ai"`

Live example: `GET /api/vehicles/757ec6cd-39fa-4bca-99d5-45e6d52610f2/`
(2015 Toyota Camry, AI):

```json
{
  "id": "757ec6cd-39fa-4bca-99d5-45e6d52610f2",
  "source": "ai",
  "name": "2015 Toyota Camry",
  "make": "Toyota",
  "brand": "Toyota",
  "model": "Camry",
  "year": 2015,
  "powertrain_type": "petrol",
  "fuel_type": "petrol",
  "engine_l": 2.5,
  "ancap_safety_rating": 5,
  "ancap_rating": 5,
  "num_seats": 5,
  "seats": 5,
  "tailpipe_co2_g_per_km": 180.0,
  "fuel_range_km": 897,
  "annual_km": 14000,
  "annual_km_default": 14000,
  "image_url": "/media/vehicle_silhouettes/large-category-sedan.png",
  "driveaway_price": 1350000,
  "resale_value_5yr_estimate": 550000,
  "resale_value_5yr": 550000,
  "resale_value": 550000,
  "resale_percent": 40.7,
  "field_sources": {"make": "ai", "tailpipe_co2_g_per_km": "ai", "driveaway_price": "ai"},
  "engine_data": {
    "total_annual_cost": 766480,
    "annual_cost_breakdown": {
      "fuel": 262080, "electricity": 0, "ctp": 57200,
      "comprehensive": 278870, "registration": 68000,
      "servicing": 47850, "tyres": 52480, "road_user_charge": 0,
      "fuel_or_energy_annual": 262080, "insurance_annual": 278870,
      "ctp_annual": 57200, "registration_annual": 68000,
      "servicing_annual": 47850, "tyres_annual": 52480,
      "ev_levy_annual": 0, "total_annual": 766480
    },
    "tailpipe_co2_g_per_km": 180.0,
    "annual_co2_kg": 2520,
    "annual_km": 14000,
    "is_estimate": true,
    "resale_value_5yr_estimate": 550000
  }
}
```

### d) Unknown id — unchanged

```bash
GET /api/vehicles/<random-uuid>/
```
```json
HTTP 404
{"detail": "Vehicle not found."}
```

---

## Key / alias reference

Every key below is **always present** (null when unknown). Aliases exist so
the mappers find a value regardless of which naming convention a code path
uses:

| Key(s) | Meaning | Notes |
|---|---|---|
| `id`, `source`, `name` | identity | `source`: `gvg` or `ai` |
| `make` = `brand` | manufacturer | |
| `model`, `year`, `variant`, `body_style` | identity | |
| `powertrain_type` = `fuel_type` | `petrol` / `diesel` / `hybrid` / `bev` / … | |
| `drive` = `drive_type` = `drivetrain` | `FWD` / `RWD` / `AWD` | |
| `num_seats` = `seats`, `doors` | integers or null | |
| `engine_l`, `battery_kwh` = `battery_capacity_kwh` | BEVs/combustion report `0.0` for the N/A one | |
| `ancap_safety_rating` = `ancap_rating` | 1–5 or null | |
| `tow_braked_kg`, `tow_unbraked_kg` | kg or null | |
| `test_cycle`, `fcai_category`, `fcai_broad` | strings | |
| `fuel_consumption_combined_l_100km` = `fuel_consumption_l_100km` = `combined_fuel_consumption_l_100km` | L/100km | |
| `tailpipe_co2_g_per_km` | g/km | |
| `wltp_range_km` | WLTP range (mostly null for combustion) | |
| `fuel_range_km`, `range_petrol_km`, `range_total_km` | usable range km | `fuel_range_km` is the safe one to render |
| `annual_km` = `annual_km_default` | km p.a. used for cost math | |
| `image_url` | curated image or silhouette | never a hotlinked photo |
| `driveaway_price` | cents, state-resolved | also `driveaway_price_by_state` (cents per state) |
| `resale_value_5yr_estimate` = `resale_value_5yr` = `resale_value`, `resale_percent` | cents + % | derived when the record has none |
| `field_sources` | per-field provenance map | see below |
| `engine_data` | running-cost block | same shape as catalogue `engine_data` |

### `field_sources` badge meanings

- `"db"` — real value from the GVG dataset
- `"ai"` — Grok-estimated (AI-search rows, or warmed spec estimates)
- `"default"` — sheet-derived assumption/default (category medians, derived
  resale, nearest-year price)
- key absent — genuinely unknown; value is null

### `engine_data` block (GVG/AI cars)

Same shape the catalogue returns, so existing cost UI works verbatim:

| Key | Meaning |
|---|---|
| `total_annual_cost` | cents p.a. (estimate) |
| `annual_cost_breakdown` | per-part cents: `fuel_or_energy_annual`, `insurance_annual`, `ctp_annual`, `registration_annual`, `servicing_annual`, `tyres_annual`, `ev_levy_annual`, `total_annual` |
| `tailpipe_co2_g_per_km`, `annual_co2_kg`, `annual_km` | as displayed |
| `is_estimate` | always `true` for GVG/AI |
| `resale_value_5yr_estimate` | cents; mirrors the top-level resale when the record has one, derived otherwise (may be null for GVG rows with no price on record — use the top-level key first) |

---

## Testing checklist

1. Add a **GVG** car to My Garage (e.g. from vehicle lookup, an older car
   like "2015 Toyota Corolla"). Open its card → image, Est. Annual Running
   Costs, Est. CO₂, Estimated km p.a., Est. fuel range, Resale value all
   populated.
2. Same for an **AI** car (search something obscure, e.g. "1998 Nissan
   Silvia", pick the AI result, add to garage).
3. Set as **Current Vehicle** → the Current Vehicle screen shows the same
   filled rows.
4. A **Carreb** car card is byte-identical to before (regression check).

## curl quick test

```bash
# GVG car (was 404 before this change)
curl -s "https://api.carreb.com.au/api/vehicles/ebeb0db5-fab2-4908-8d9a-758e2d819837/" | jq '.source, .brand, .engine_data.total_annual_cost, .resale_value_5yr_estimate'

# AI car
curl -s "https://api.carreb.com.au/api/vehicles/757ec6cd-39fa-4bca-99d5-45e6d52610f2/" | jq '.source, .brand, .engine_data.total_annual_cost'

# Unknown id
curl -s -o /dev/null -w "%{http_code}\n" "https://api.carreb.com.au/api/vehicles/00000000-0000-0000-0000-000000000000/"
# → 404
```
