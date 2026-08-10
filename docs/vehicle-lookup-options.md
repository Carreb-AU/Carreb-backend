# Vehicle Internet Lookup — Implementation Runbook (Option A)

> Status: **Option A selected and implemented** per client decision note (Gio, 8 Aug 2026).  
> Apex DB was declined at launch. We import the Green Vehicle Guide CSV/XLSX directly.

## What the client wants

1. **Current-vehicle search must look at ALL vehicles**, not only the Carreb catalogue. Carreb stores new (2025/2026) vehicles for sale today; older/prior-year vehicles live in the GVG import table.
2. **Pre-populate every field the CORE engine needs** for cost / CO₂ comparison against new garage vehicles: fuel consumption, CO₂, powertrain, body style, seats, plus state-level cost components (CTP, comprehensive insurance, registration, servicing, tyres).
3. **Use category cost defaults** when a GVG record has no matching Carreb catalogue row (Option A from the decision note).
4. **Quarterly refresh cadence**; re-download and re-import from greenvehicleguide.gov.au.
5. **No Apex DB at launch**; revisit only if Carreb expands beyond Australia.

## Where each year range lives

| Year range | Location | Source |
|------------|----------|--------|
| 2025–2026 (new, for-sale) | `Vehicle` table | Carreb ETL workbook |
| 2004–2025 (prior-year specs) | `GreenVehicleGuideRecord` table | `docs/GVG-Vehicles-2004-2025.xlsx` |
| 1986–2003 (older vehicles) | `GreenVehicleGuideRecord` table | `docs/FuelConsumptionGuide1986-2003.csv` |

## Architecture

```
User query
    │
    ▼
CurrentVehicleSearchView
    │
    ├─ Search local Vehicle catalogue (Carreb new vehicles)
    ├─ Search GreenVehicleGuideRecord (GVG import)
    │
    ▼
Merge + deduplicate by (year, make, model, variant)
    │
    ▼
Return unified list; Carreb rows take priority over GVG rows
```

When a user selects a GVG record as their current vehicle:
- `CurrentVehicle.green_vehicle_guide_record` is set.
- `build_vehicle_like_from_gvg(record, state)` creates a duck-typed object that `calculate_core_rating()` can consume.
- Cost gaps (insurance, CTP, rego, servicing, tyres) are filled from `CategoryCostDefault` medians derived from the Carreb workbook.

## Files changed

- `apps/vehicles/models.py` — added `CategoryCostDefault`, extended `GreenVehicleGuideRecord`, kept existing `Vehicle`.
- `apps/vehicles/admin.py` — registered `DataSource`, `GreenVehicleGuideRecord`, `CategoryCostDefault`; added admin import action.
- `apps/vehicles/services/gvg_import.py` — import service, mappings, CO₂ estimation, `VehicleLike` builder.
- `apps/vehicles/management/commands/import_gvg_data.py` — management command.
- `apps/vehicles/migrations/0006_datasource_categorycostdefault_greenvehicleguiderecord.py` — creates new tables.
- `apps/mygarage/models.py` — added `CurrentVehicle.green_vehicle_guide_record` FK.
- `apps/mygarage/serializers.py` — `CurrentVehicleCreateSerializer` accepts `green_vehicle_guide_record_id`.
- `apps/mygarage/views.py` — `CurrentVehicleSearchView` merges/dedups; `CurrentVehicleView` saves GVG selection; `_build_calculated_vehicle_response` wires GVG into CORE rating.
- `apps/mygarage/migrations/0007_currentvehicle_green_vehicle_guide_record.py` — adds the FK.

## Getting the source files

1. **Current GVG (2004–2025)**  
   Download the `Vehicles 2004-2025` workbook from <https://greenvehicleguide.gov.au> and save as:  
   `docs/GVG-Vehicles-2004-2025.xlsx`

2. **Older vehicles (1986–2003)**  
   Go to **Tools → Search older vehicles** on greenvehicleguide.gov.au, export CSV, and save as:  
   `docs/FuelConsumptionGuide1986-2003.csv`

3. **Carreb workbook (for cost defaults)**  
   Keep in project root:  
   `Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx`

## How to import

### Option A — Django Admin (button)

1. Log into Django admin.
2. Go to **Vehicles → Data sources**.
3. Select any DataSource row(s) and choose the action **“Import GVG data from docs/ folder”**.
4. The action imports category defaults + both GVG datasets. It is idempotent: re-running updates `DataSource.retrieved_at` and appends new GVG rows (it does not clear existing rows unless you use `--clear`).

### Option B — Management command

Run on your server environment (Postgres):

```bash
python manage.py import_gvg_data all \
  --workbook "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx" \
  --gvg-xlsx docs/GVG-Vehicles-2004-2025.xlsx \
  --old-csv docs/FuelConsumptionGuide1986-2003.csv
```

Other modes:

```bash
# Only category cost defaults
python manage.py import_gvg_data defaults --workbook "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"

# Only current GVG (2004–2025)
python manage.py import_gvg_data current --gvg-xlsx docs/GVG-Vehicles-2004-2025.xlsx

# Only older CSV (1986–2003)
python manage.py import_gvg_data older --old-csv docs/FuelConsumptionGuide1986-2003.csv

# Wipe and re-import a dataset
python manage.py import_gvg_data all ... --clear
```

## Migration commands to run

```bash
python manage.py migrate vehicles 0006
python manage.py migrate mygarage 0007
```

Or simply:

```bash
python manage.py migrate
```

## What the importer does

### Powertrain mapping

GVG fuel-type strings are normalised to Carreb `PowertrainType` choices:

| GVG fuel string contains | Carreb powertrain |
|--------------------------|-------------------|
| `plug-in electric` / `phev` | `phev` |
| `pure electric` / `electric` | `bev` |
| `hydrogen` / `fcev` | `fcev` |
| `electric/petrol` / `electric/diesel` | `hybrid` |
| `mild hybrid` | `mild_hybrid` |
| `diesel` | `diesel` |
| `petrol` / `lpg` / `cng` | `petrol` |
| anything else | `petrol` (fallback) |

### Body style / FCAI category inference

GVG body styles are mapped to Carreb vocabulary and then to an FCAI category for cost-default lookup:

| GVG body style | Carreb body style | FCAI category |
|------------------|-------------------|---------------|
| Hatch / Hatchback | `hatchback` | `Medium` (passenger) |
| Sedan | `sedan` | `Medium` |
| Wagon | `wagon` | `Medium` |
| SUV | `suv` | `SUV-Medium` / `SUV-Large` by seats |
| Utility / Ute | `ute` | `Ute` |
| Van | `van` | `Van` |
| Cab-chassis | `cab chassis` | `Ute` |
| Coupe / Convertible | `coupe` / `convertible` | `Sports` |
| People Mover / Light bus | `people mover` | `People-Mover` |

The mapping is heuristic; if you need finer passenger-car sizing, we can add a model-name / dimension lookup later.

### 1986–2003 CO₂ estimation

The older CSV does not include CO₂. The importer estimates it from fuel type and combined fuel consumption:

- Petrol / LPG / CNG → `2.31 kg CO₂/L`
- Diesel → `2.68 kg CO₂/L`
- LPG → `1.51 kg CO₂/L`

Formula: `CO₂ (g/km) = (L/100km × factor) / 100`

These records are flagged with `test_cycle='ADR'` and `source_dataset='GVG-OLDER-8603'`.

### Category cost defaults

For every `(fcai_category, state)` pair, the importer reads `COO_Component_Breakdown` from the Carreb workbook and stores the **median** of:

- `ctp_pa`
- `comprehensive_pa`
- `registration_pa`
- `maintenance_pa` (stored as p.a.)
- `tyre_cost_pa` (stored as p.a.)
- `fuel_cost_pa`
- `electricity_cost_pa`
- `ev_levy_pa`

It also pre-computes `servicing_5yr_estimate = maintenance_pa × 5` and `tyre_replacement_estimate = tyre_cost_pa × 5`.

When a GVG record is used for a CORE rating, these defaults are applied to the user’s selected state.

### Corrupt-row handling

A small number of rows in the 2004–2025 workbook have shifted columns (a comma inside `Variant` caused `FuelType` to become numeric). The importer skips any row where `FuelType` looks like a bare number. Skipped rows are reported in the command output.

## API behaviour changes

### `POST /api/mygarage/current-vehicle/search/`

Returns a merged list with `source: "carreb"` or `source: "gvg"`.

Example response shape:

```json
[
  {
    "id": "uuid",
    "source": "carreb",
    "year": 2026,
    "make": "Toyota",
    "model": "Camry",
    "variant": "Ascent",
    "body_style": "sedan",
    "powertrain_type": "hybrid",
    "fuel_consumption_per_100km": 4.2,
    "tailpipe_co2_g_per_km": 96,
    "image_url": "https://...",
    "name": "2026 Toyota Camry Ascent"
  },
  {
    "id": "uuid",
    "source": "gvg",
    "year": 2015,
    "make": "Toyota",
    "model": "Camry",
    "variant": "Altise",
    "body_style": "sedan",
    "powertrain_type": "petrol",
    "fuel_consumption_per_100km": 7.8,
    "tailpipe_co2_g_per_km": 183,
    "image_url": null,
    "name": "2015 Toyota Camry Altise"
  }
]
```

### `POST /api/mygarage/current-vehicle/`

Accepts either:

```json
{
  "vehicle_catalogue_id": "<uuid>"
}
```

or:

```json
{
  "green_vehicle_guide_record_id": "<uuid>",
  "state": "NSW"
}
```

If both IDs are provided the request is rejected.

## Verification checklist

After running migrations and the importer:

1. `python manage.py shell`:

   ```python
   from apps.vehicles.models import GreenVehicleGuideRecord, CategoryCostDefault
   GreenVehicleGuideRecord.objects.count()          # expect ~28k rows
   CategoryCostDefault.objects.count()              # expect one row per (category, state)
   ```

2. Search endpoint returns both `source: "carreb"` and `source: "gvg"` results.
3. Selecting a GVG record as current vehicle produces a CORE rating in the response.

## Costs

- **GVG data:** free (Australian Government).
- **Hosting:** extra rows in Postgres — negligible (~28k rows, <50 MB).
- **Engineering:** one-time importer + search wiring (done).
- **Apex DB:** not used at launch.

## Open / out of scope

- **2FA always optional** — not addressed in this change.
- **New-car search tiers** (`Registered & Unpaid/Free Member = SCF only`; `Registered+Paid = all features`) — not addressed here; still needs gating on `users.subscription_tier`.
- **CORE Dial numbers missing** — not addressed here.
- **Print / PDF / table width issues** in the admin/frontend — separate UI/CSS work.
