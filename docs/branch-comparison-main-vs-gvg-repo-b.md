# Branch Comparison: `main` vs `gvg-repo-b`

> TL;DR: `main` uses a **rich, CORE-integrated GVG model** with category cost defaults. `gvg-repo-b` uses a **lighter GVG lookup table** and relies on the existing manual-entry path. Both answer "find my older current car", but the data shape, search algorithm, and rating wiring are different.

---

## 1. What each branch does at a glance

| Area | `main` (our work) | `gvg-repo-b` (external repo) |
|------|-------------------|------------------------------|
| **Goal** | Current-vehicle search across Carreb catalogue + older GVG records | Same goal, different implementation |
| **GVG table** | `GreenVehicleGuideRecord` with full cost fields + `CategoryCostDefault` + `DataSource` | `GreenVehicleGuideRecord` with only identity + 2 efficiency fields; no cost defaults or source registry |
| **Import command** | `import_gvg_data all` (parses workbook + GVG XLSX + old CSV, builds category defaults) | `import_gvg_csv` (header-driven CSV only, no workbook dependency) |
| **Search algorithm** | Token `icontains` on `make/model/year` | Token `icontains` on catalogue + **PostgreSQL `pg_trgm` trigram similarity** on GVG `search_text` |
| **CurrentVehicle link** | FK to `Vehicle` **or** FK to `GreenVehicleGuideRecord` | FK to `Vehicle` only; GVG record is saved via `gvg_record_id` into `manual_entry_data` |
| **Rating integration** | Builds a `VehicleLike` duck-typed object from GVG + category defaults, then calls CORE engine directly | GVG record is turned into `manual_entry_data`; CORE engine uses existing manual-entry / benchmark path |
| **Search response IDs** | `id` is the real UUID (`Vehicle.id`) or UUID (`GreenVehicleGuideRecord.id`), `source` = `carreb` or `gvg` | Catalogue uses `id` (UUID); GVG uses synthetic `id: "gvg-<pk>"` plus separate integer `gvg_record_id` |
| **Set-current payload** | `vehicle_catalogue_id` **or** `green_vehicle_guide_record_id` (UUID) | `vehicle_catalogue_id` **or** `gvg_record_id` (integer) |

---

## 2. Data-model differences

### `main`

```python
# 3 new models
class DataSource: ...               # source registry with admin import action
class CategoryCostDefault: ...      # per-category/state cost defaults
class GreenVehicleGuideRecord: ...  # full copy of GVG + cost fields

# CurrentVehicle gets a second FK
class CurrentVehicle:
    vehicle_catalogue = FK(Vehicle)
    green_vehicle_guide_record = FK(GreenVehicleGuideRecord)
```

- GVG record is a **first-class citizen** in the garage.
- `CategoryCostDefault` supplies insurance/CTP/rego/servicing/tyres when GVG does not have them.
- `gvg_import.py` builds a `VehicleLike` object so the existing `calculate_core_rating()` engine runs unchanged.

### `gvg-repo-b`

```python
# 1 new model, 2 choices
class GreenVehicleGuideRecord: ...  # identity + fuel/CO2 only
class GVGSourceDataset(TextChoices): ...

# CurrentVehicle loses the GVG FK
class CurrentVehicle:
    vehicle_catalogue = FK(Vehicle)
    # green_vehicle_guide_record FK removed
    manual_entry_data = JSONField(...)  # GVG record is copied here
```

- GVG record is treated as **lookup data**, not a garage entity.
- On `POST /api/my-garage/current-vehicle/`, the view copies GVG fields into `manual_entry_data`.
- CORE rating then falls back to the existing manual-entry/benchmark calculation (whatever path `calculate_core_rating()` already had for `manual_entry_data`).

---

## 3. Search differences

| `main` | `gvg-repo-b` |
|--------|--------------|
| Splits query into tokens, requires every token to match `make`, `model`, or `year` | Splits query, uses `brand/model/variant__icontains` for catalogue and `TrigramSimilarity('search_text', needle)` for GVG |
| Simple but brittle: a typo or model nickname returns nothing | Fuzzy: `"corolla"` matches close spellings and partial model names fast |
| No special DB extension required | Requires `pg_trgm` extension and `django.contrib.postgres` |
| Returns up to 10 Carreb + up to 10 GVG, merged, deduped, capped at 15 | Returns up to 10 total, Carreb wins on collision |

**Important:** `gvg-repo-b` uses **integer** `gvg_record_id` in the search result and expects an **integer** back in the set-current payload.

---

## 4. Migration conflict (must be resolved before merging)

```
main:        vehicles/0006_datasource_categorycostdefault_greenvehicleguiderecord.py
gvg-repo-b:  vehicles/0006_vehicle_indexes.py
gvg-repo-b:  vehicles/0007_greenvehicleguiderecord.py
```

Both branches claim migration `0006` in `apps/vehicles`. You **cannot merge them** without renaming one set of migrations and rebuilding history. Whichever branch you keep, the final migration chain must be sequential and unique.

---

## 5. Security & hardening extras on `gvg-repo-b`

`gvg-repo-b` also ships changes unrelated to GVG:

- `VehicleDataUploadView` now requires `IsAdminUser` (was `AllowAny`).
- `CoreRatingCalculateView`, `CoreRatingBatchView`, `CoreSearchView` strip `est_cost_difference` for anonymous users.
- `VehicleDetailSerializer` hides dollar/cost fields for anonymous users.
- `config/settings/prod.py` turns on `SECURE_SSL_REDIRECT`, secure cookies, HSTS, lowers Sentry sample rate, disables PII.
- `apps/freematch/services.py` removes the `is_suggested` flag from match responses.

These are mostly sensible security fixes, but they are **side effects** of the external repo and should be reviewed separately.

---

## 6. Which one should you keep?

### Keep `main` if:

- You want GVG records to be **fully CORE-scored** with proper category cost defaults.
- You want admin-import from the existing workbook/XLSX workflow.
- You want a deterministic, explainable token search (no trigram magic).
- You are comfortable with the richer model and migration.

### Keep `gvg-repo-b` if:

- You want **fuzzy type-ahead search** (better UX for misspellings / partial model names).
- You prefer a **smaller data model** and want to lean on the existing manual-entry path.
- You are OK with importing only CSVs and do not need the workbook-based category defaults.
- You are ready to resolve the migration conflict and enable `pg_trgm`.

### Recommended hybrid (what we are doing):

Adopt `gvg-repo-b`'s **trigram search** and `search_text` GIN index (better UX), but wire it to `main`'s richer `GreenVehicleGuideRecord` + `CategoryCostDefault` + `VehicleLike` rating path. This gives fast fuzzy search *and* accurate cost/CO2 comparisons.

**Status:** We have ported the trigram search to `main` as migration `0007_greenvehicleguiderecord_search_text`. `main` keeps its own model, import command, and CORE rating path.

---

## 7. Why the screenshot shows "No matching vehicles"

In the screenshot the frontend calls:

```
GET /api/vehicles/5be318ce-a90f-444a-8a53-5ac815a9d68a/
```

That endpoint only exists for **Carreb catalogue** vehicles. The selected result came from GVG, so the UUID is either a GVG UUID (`main`) or a synthetic `gvg-<pk>` string (`gvg-repo-b`). Neither is a `Vehicle` UUID, so `GET /api/vehicles/<id>/` returns 404.

The frontend must instead call `POST /api/my-garage/current-vehicle/` and send the correct field based on `source`:

| Branch | Carreb field | GVG field |
|--------|--------------|-----------|
| `main` | `vehicle_catalogue_id` (UUID) | `green_vehicle_guide_record_id` (UUID) |
| `gvg-repo-b` | `vehicle_catalogue_id` (UUID) | `gvg_record_id` (integer) |

If your frontend currently calls `/api/vehicles/<id>/` after the user selects a search result, that is the bug causing "No matching vehicles". Update it to use `/api/my-garage/current-vehicle/` as shown in `docs/frontend-integration-current-vehicle-search.md`.
