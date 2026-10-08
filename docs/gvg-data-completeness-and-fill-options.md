# GVG Vehicle Data Completeness & Fill Options

> For client review. This document explains what we have for each imported vehicle age group, what is missing, what the backend can fill automatically, and how the client can fill the rest manually.

---

## The two imported GVG datasets

| Dataset | Years | File | Records (current import) | Source |
|---------|-------|------|--------------------------|--------|
| **Fuel Consumption Guide** | 1986 – 2003 | `docs/FuelConsumptionGuide1986-2003.csv` | ~10,000 | Australian Government (older CSV) |
| **Green Vehicle Guide** | 2004 – 2025 | `docs/GVG-Vehicles-2004-2025.xlsx` | ~18,000 | Australian Government (current XLSX) |

Carreb’s own catalogue (`Vehicle` model) covers **new vehicles for sale today** (2025–2026). It is the source of truth for fixed-band CORE scores, detailed cost components, and images.

---

## Dataset 1: 1986 – 2003 (Fuel Consumption Guide CSV)

### What the CSV gives us

| Field | Status | Notes |
|-------|--------|-------|
| `make` | ✅ Available | e.g. `Toyota` |
| `model` | ✅ Available | e.g. `Camry` |
| `year` | ✅ Available | Model year |
| `body_style` | ✅ Mapped | Mapped from CSV body style to Carreb vocabulary (sedan, wagon, SUV, etc.) |
| `num_seats` | ✅ Available | If present in CSV |
| `fuel_type` / `powertrain_type` | ✅ Mapped | petrol, diesel, LPG, etc. |
| `fuel_consumption_combined_l_100km` | ✅ Available | Combined L/100km |
| `fuel_consumption_urban_l_100km` | ✅ Available | City cycle |
| `fuel_consumption_extra_urban_l_100km` | ✅ Available | Highway cycle |
| `tailpipe_co2_g_per_km` | ✅ Estimated | Calculated from fuel type + consumption because CSV does not include CO₂ for this era |
| `transmission` | ✅ Available | If present |

### What is missing

| Field | Why it is missing | Can we fill it? |
|-------|-------------------|-----------------|
| `variant` | CSV does not include trim/variant | ❌ No source for 1986–2003 |
| `engine_l` | CSV does not include engine displacement | ❌ No source |
| `battery_kwh`, `electric_range_km` | These vehicles are not EVs/PHEVs | ❌ Not applicable |
| `driveaway_price` / `driveaway_price_by_state` | No price data in CSV | ❌ Not meaningful for 30+ year old cars; leave `null` |
| `image_url` | No official image source | ❌ Use generic placeholder |
| `ancap_safety_rating` | ANCAP did not exist for most of this period | ❌ Leave `null` |
| `insurance_estimate_by_state` | No per-vehicle insurance data | ✅ Auto-filled from `CategoryCostDefault` (category + state average) |
| `ctp_by_state` | No per-vehicle CTP data | ✅ Auto-filled from `CategoryCostDefault` |
| `registration_by_state` | No per-vehicle rego data | ✅ Auto-filled from `CategoryCostDefault` |
| `fuel_cost_by_state` | No per-vehicle fuel price data | ✅ Auto-filled from `CategoryCostDefault` |
| `servicing_5yr_estimate` | No per-vehicle servicing data | ✅ Auto-filled from `CategoryCostDefault` |
| `tyre_replacement_estimate` | No per-vehicle tyre data | ✅ Auto-filled from `CategoryCostDefault` |
| `resale_value_5yr_estimate` | No depreciation data for this era | ❌ Not meaningful; leave `null` |
| `mode_data_by_state` / CORE stars | Outside the Carreb workbook scoring range | ❌ Use percentile fallback scoring instead of fixed-band stars |
| `ev_levy_by_state` | Not applicable | ✅ `0` |

### What the user sees

- Search works (trigram fuzzy search on `year make model`).
- The comparison page shows **category-level estimates** for running costs.
- CO₂ is estimated from fuel consumption.
- The result is flagged as an estimate and should show a generic placeholder image.

---

## Dataset 2: 2004 – 2025 (Green Vehicle Guide XLSX)

### What the XLSX gives us

| Field | Status | Notes |
|-------|--------|-------|
| `make` | ✅ Available | |
| `model` | ✅ Available | |
| `variant` | ✅ Available | Trim/variant is present |
| `year` | ✅ Available | Model release year |
| `body_style` | ✅ Mapped | Mapped from `BodyStyle` to Carreb vocabulary |
| `num_seats` | ✅ Available | `SeatingCapacity` |
| `fuel_type` / `powertrain_type` | ✅ Mapped | Includes petrol, diesel, hybrid, PHEV, BEV, FCEV |
| `fuel_consumption_combined_l_100km` | ✅ Available | |
| `fuel_consumption_urban_l_100km` | ✅ Available | |
| `fuel_consumption_extra_urban_l_100km` | ✅ Available | |
| `electricity_consumption_wh_per_km` | ✅ Available | For EVs/PHEVs; converted to kWh/100km |
| `electric_range_km` | ✅ Available | For EVs/PHEVs |
| `tailpipe_co2_g_per_km` | ✅ Available | For most records |
| `engine_l` | ✅ Available | `EngineDisplacement` |
| `battery_kwh` | ✅ Available | For EVs/PHEVs |
| `transmission` | ✅ Available | `TransmissionTypeDescription` |
| `annual_fuel_cost` | ✅ Available | For many current-model rows; used as vehicle-specific fuel cost |
| `test_cycle` | ✅ Available | ADR |

### What is missing

| Field | Why it is missing | Can we fill it? |
|-------|-------------------|-----------------|
| `driveaway_price` / `driveaway_price_by_state` | GVG does not publish sale prices | ⚠️ **Partially** — can be estimated for 2024–2025 by matching to the Carreb workbook; for older years, leave `null` |
| `image_url` | GVG does not include images | ❌ Use generic placeholder |
| `ancap_safety_rating` | Not in GVG | ⚠️ **Partially** — can import ANCAP public ratings for 2004+ models |
| `insurance_estimate_by_state` | No per-vehicle insurance data | ✅ Auto-filled from `CategoryCostDefault` |
| `ctp_by_state` | No per-vehicle CTP data | ✅ Auto-filled from `CategoryCostDefault` |
| `registration_by_state` | No per-vehicle rego data | ✅ Auto-filled from `CategoryCostDefault` |
| `servicing_5yr_estimate` | No per-vehicle servicing data | ✅ Auto-filled from `CategoryCostDefault` |
| `tyre_replacement_estimate` | No per-vehicle tyre data | ✅ Auto-filled from `CategoryCostDefault` |
| `resale_value_5yr_estimate` | GVG does not include depreciation | ⚠️ **Partially** — can estimate from workbook depreciation curves for 2004–2025 |
| `mode_data_by_state` / CORE stars | GVG records are not in the Carreb scoring workbook | ⚠️ **Partially** — exact fixed-band stars are only possible for 2024–2025 models that also exist in the Carreb workbook; older years use percentile fallback |
| `ev_levy_by_state` | Not in GVG | ✅ `0` or category default |

---

## What we can do automatically right now

1. **Category defaults** — already live. Every GVG record gets insurance/CTP/rego/servicing/tyre/fuel/EV-levy values from `CategoryCostDefault`.
2. **Vehicle-specific fuel cost** — already live for 2004+ GVG records that include `AnnualFuelCost`.
3. **CO₂ estimate** — already live for 1986–2003 records.

## What we can add next (backend work)

| Feature | What it fills | Records affected | Effort |
|---------|---------------|------------------|--------|
| **Match GVG → Carreb Vehicle** | driveaway, insurance/CTP/rego/servicing/tyre, fuel/electricity, `mode_data_by_state`, image, ANCAP | 2024–2025 GVG records that overlap with Carreb catalogue | ~1 day |
| **Model-year average table** | More accurate running-cost estimates than broad category | 2004–2023 GVG records | ~2 days |
| **Depreciation-based driveaway/resale** | Estimated driveaway and resale credit | 2004–2023 | ~1 day |
| **ANCAP import** | Safety ratings | 2004+ where ANCAP has data | ~1–2 days (depends on data source) |
| **Generic image placeholders** | UI placeholder | All GVG records | 30 min |

## Manual fill-up option

If the client wants to improve specific high-priority vehicles, we can add a **manual enrichment** feature.

### How it would work

1. Add a new `GVGDataEnrichment` model (or JSON `manual_data` field on `GreenVehicleGuideRecord`) that stores overrides per record:
   - `driveaway_price_estimate`
   - `insurance_estimate_by_state`
   - `ctp_by_state`
   - `registration_by_state`
   - `servicing_5yr_estimate`
   - `tyre_replacement_estimate`
   - `resale_value_5yr_estimate`
   - `ancap_safety_rating`
   - `image_url`
   - `notes`

2. Expose it in Django Admin so the client can search by make/model/year and edit values directly.

3. Alternatively, add a management command that accepts an Excel/CSV upload in a simple format:

   ```csv
   make,model,variant,year,state,driveaway,insurance,ctp,registration,servicing,tyres,ancap,image_url
   ```

   The command matches rows to GVG records and stores the overrides.

4. The `VehicleLike` wrapper uses manual overrides first, then category defaults, so the comparison page reflects the manually entered values.

### Cost / effort

- Backend model + admin: **~3–4 hours**
- Bulk upload command: **~3–4 hours**
- Frontend indicator (“data enriched by Carreb team”): **~1 hour**

This gives the client full control over the most important vehicles without waiting for a full automated data source.

---

## Recommended path forward

1. **Short term (this week):** Keep category defaults for 1986–2003 and 2004–2023; add a `data_quality` flag to the API so the UI can show “estimate only” for older cars.
2. **Medium term:** Add the GVG → Carreb matching step for 2024–2025 overlap vehicles.
3. **If the client wants better numbers for specific popular older models:** Build the manual enrichment admin + upload command.
4. **Long term:** Import ANCAP ratings and model-year averages if budget allows.
