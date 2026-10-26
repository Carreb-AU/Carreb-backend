"""
Import the "Consolidated Vehicles v6.4" sheet into the Vehicle catalogue.

Sheet layout (one row per vehicle × state × CORE mode):
  - scalar vehicle fields repeat on every row (taken from the first row)
  - state-level costs repeat per mode (last write wins, values are constant)
  - mode-level figures (mode COO, scores, stars) vary per row and are nested
    into mode_data_by_state[STATE][MODE_LETTER]

Money discipline:
  - *_by_state JSON fields and 5-year estimates are stored as integer cents
  - mode_data money keys stay float dollars (rating_engine multiplies by 100)

Upserts on the natural key (brand, model, variant, year) so UUIDs — and the
GarageVehicle FKs that point at them — stay stable across re-imports.
"""

import datetime
import math
import os
from typing import Dict, Optional

import pandas as pd

from apps.vehicles.models import (
    ConsolidatedVehicleRow,
    PowertrainType,
    TestCycle,
    Vehicle,
)

SHEET_NAME = "Consolidated Vehicles v6.4"
SPOTLIGHT_SHEET_NAME = "Spotlights"  # added in the 13-Oct-26 workbook

# Workbook metadata keywords that are never real vehicle makes (defensive;
# the consolidated sheet is expected to be clean).
_JUNK_MAKE_KEYWORDS = (
    "_",
    "section",
    "computed",
    "internal",
    "primary_source_table",
    "insurancedefaults",
    "energytypecostmodifiers",
    "registrationdefaults",
    "scaling_factor",
)

NOT_IN_SOURCE = "not in source"

# Client convention (Forensic #28, flagged in every BEV row's data_flags):
# BEV energy use is a flat 180 Wh/km = 18.0 kWh/100km for ALL BEVs — the
# sheet's electricity_cost_pa figures are computed on this flat rate (verified:
# every battery-known BEV's cost implies ~17.8 kWh/100km). The sheet provides
# no per-vehicle BEV FE (fe_basis = "n/a (BEV) — 0 per v6.3.4 convention").
BEV_FLAT_KWH_PER_100KM = 18.0

# Every field the importer owns; used for bulk_update on re-import.
# NOTE: image_url is deliberately excluded — the consolidated sheet carries no
# image column, so updating it here would wipe URLs fetched by other pipelines
# (fetch_vehicle_images / set_vehicle_fallback_images). Existing values are kept.
VEHICLE_UPDATE_FIELDS = [
    "body_style", "num_seats", "powertrain_type",
    "fcai_category", "fcai_broad", "energy_norm", "drive", "engine_l",
    "battery_kwh", "driveaway_price_by_state", "fuel_consumption_per_100km",
    "electricity_consumption_per_100km", "tailpipe_co2_g_per_km",
    "wltp_range_km", "test_cycle", "annual_km_default",
    "insurance_estimate_by_state", "ctp_by_state", "registration_by_state",
    "servicing_5yr_estimate", "tyre_replacement_estimate",
    "resale_value_5yr_estimate", "total_5yr_cost_of_ownership_by_state",
    "fuel_cost_by_state", "electricity_cost_by_state", "ev_levy_by_state",
    "base_coo_by_state", "components_sum_by_state", "mode_data_by_state",
    "is_scoring_outlier", "scoring_version", "provenance",
    "au_launch", "price_type", "research_status", "source_name",
    "internal_notes", "source_tab", "cost_category", "energy_type",
    "finance_apr_pct", "total_interest_5yr", "finance_fees_5yr",
    "finance_cost_5yr", "retention_factor", "drivetrain", "fuel_tank_l",
    "range_battery_km", "range_petrol_km", "range_total_km", "range_basis",
    "range_ladder_step", "range_estimated_badge", "range_prior_value",
    "price_basis", "fe_basis", "co2_basis", "assumption_fills",
    "data_flags", "range_research_note",
    "co2_energy_cycle_g_per_km", "spotlight_data",
    "transmission", "doors", "base_fuel", "phev_fuel_consumption_l100",
    "energy_consumption_wh_km", "co2_energy_cycle_basis",
    "maintenance_5yr_detail", "is_suppressed",
]


def _safe_float(val) -> Optional[float]:
    if val is None or pd.isna(val) or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> Optional[int]:
    if val is None or pd.isna(val) or val == "":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _safe_str(val) -> str:
    if val is None or pd.isna(val):
        return ""
    return str(val).strip()


def _safe_bool(val) -> bool:
    if val is None or pd.isna(val) or val == "":
        return False
    return str(val).strip().lower() in ("true", "yes", "1")


def _dollars_to_cents(val) -> Optional[int]:
    f = _safe_float(val)
    if f is None:
        return None
    return int(round(f * 100))


def _json_safe(val):
    """Convert a sheet cell to a JSON-safe value (None/NaN -> None, numpy
    scalars -> python, dates -> ISO strings, anything else -> str)."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    try:
        import numpy as np
        if isinstance(val, np.generic):
            val = val.item()
    except ImportError:  # pragma: no cover - pandas pulls numpy in always
        np = None
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    if isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
        return val.isoformat()
    if isinstance(val, (bool, int, float, str)):
        return val
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    return str(val)


def _maintenance_5yr_detail(base) -> Optional[dict]:
    """Per-year servicing detail (cents) from the 21-Oct maintenance columns."""
    detail = {}
    for i in range(1, 6):
        cents = _dollars_to_cents(base.get(f"maintenance_yr{i}"))
        if cents is not None:
            detail[f"yr{i}_cents"] = cents
    total = _dollars_to_cents(base.get("maintenance_5yr_total"))
    if total is not None:
        detail["total_cents"] = total
    tier = _safe_str(base.get("maintenance_source_tier"))
    if tier:
        detail["source_tier"] = tier
    basis = _safe_str(base.get("maintenance_basis"))
    if basis:
        detail["basis"] = basis
    return detail or None


def _not_in_source(val) -> Optional[str]:
    """'Not in source' sentinel → None."""
    s = _safe_str(val)
    if s.lower() == NOT_IN_SOURCE:
        return None
    return s


def map_powertrain(raw: str) -> str:
    """Map the consolidated sheet's Fuel Type vocabulary to PowertrainType.

    Covers sheet values: petrol, diesel, Electric, bev, hybrid, phev, mhev,
    reev. REEV (range extender) has no enum value — mapped to HYBRID as the
    closest series-hybrid classification.
    """
    ft = _safe_str(raw).lower()
    if not ft:
        return PowertrainType.PETROL
    if "phev" in ft or "plug-in" in ft:
        return PowertrainType.PHEV
    if "reev" in ft or "range ext" in ft:
        return PowertrainType.HYBRID
    if "bev" in ft or ft == "electric" or "pure electric" in ft:
        return PowertrainType.BEV
    if "mhev" in ft or "mild" in ft:
        return PowertrainType.MILD_HYBRID
    if "hev" in ft or "hybrid" in ft:
        return PowertrainType.HYBRID
    if "fcev" in ft or "hydrogen" in ft:
        return PowertrainType.FCEV
    if "diesel" in ft:
        return PowertrainType.DIESEL
    return PowertrainType.PETROL


def map_body_style(raw: str) -> str:
    """Normalise the sheet's rich Body Type vocabulary into Carreb's."""
    from apps.vehicles.services.gvg_import import map_body_style as _gvg_map
    return _gvg_map(raw)


def _is_junk_make(make) -> bool:
    if pd.isna(make):
        return True
    text = str(make).strip().lower()
    if not text:
        return True
    return any(kw in text for kw in _JUNK_MAKE_KEYWORDS)


def _load_spotlights(filepath: str) -> Dict[tuple, dict]:
    """Read the "Spotlights" sheet into {(make, model, variant, year): data}.

    Returns an empty dict when the sheet is absent (pre-13-Oct workbooks) so
    older files keep importing cleanly.
    """
    try:
        df = pd.read_excel(filepath, sheet_name=SPOTLIGHT_SHEET_NAME)
    except ValueError:
        return {}

    out: Dict[tuple, dict] = {}
    for _, row in df.iterrows():
        make = _safe_str(row.get("Make"))
        if not make or _is_junk_make(make):
            continue
        key = (
            make,
            _safe_str(row.get("Model")),
            _safe_str(row.get("Variant")),
            str(_safe_int(row.get("Year")) or ""),
        )
        out[key] = {
            "range_kings": _safe_bool(row.get("spotlight_range_kings")),
            "green_lean": _safe_bool(row.get("spotlight_green_lean")),
            "unicorn_match": _safe_bool(row.get("spotlight_unicorn_match")),
            "category_sweep": _safe_bool(row.get("spotlight_category_sweep")),
            "core_allstars": _safe_bool(row.get("spotlight_core_allstars")),
            "count": _safe_int(row.get("spotlight_count")) or 0,
            "badges": _safe_str(row.get("spotlight_badges")),
            "version": _safe_str(row.get("spotlight_version")),
        }
    return out


def parse_consolidated_sheet(filepath: str):
    """Parse the sheet into (vehicles, skipped, source_rows).

    vehicles: list of unsaved Vehicle instances (one per natural key).
    skipped: number of non-vehicle rows dropped.
    source_rows: list of dicts for ConsolidatedVehicleRow creation (one per
    source data row of a non-junk group); empty when the workbook has no
    listing_id column (pre-21-Oct layouts).
    """
    df = pd.read_excel(filepath, sheet_name=SHEET_NAME)
    spotlights = _load_spotlights(filepath)
    has_listing_id = "listing_id" in df.columns
    has_suppression = "is_suppressed" in df.columns
    skipped = 0
    vehicles = []
    source_rows = []

    for (make, model, variant, year), group in df.groupby(
        ["Make", "Model", "Variant", "Year"], dropna=False, sort=False
    ):
        if _is_junk_make(make):
            skipped += len(group)
            continue

        base = group.iloc[0]
        spotlight_key = (
            _safe_str(make),
            _safe_str(model),
            _safe_str(variant),
            str(_safe_int(year) or ""),
        )
        natkey = (
            _safe_str(make), _safe_str(model), _safe_str(variant),
            _safe_int(year) or 0,
        )

        # ---- per-state + per-mode structures --------------------------------
        driveaway_by_state: Dict[str, int] = {}
        base_coo_by_state: Dict[str, int] = {}
        fuel_cost_by_state: Dict[str, int] = {}
        electricity_cost_by_state: Dict[str, int] = {}
        ctp_by_state: Dict[str, int] = {}
        insurance_by_state: Dict[str, int] = {}
        registration_by_state: Dict[str, int] = {}
        ev_levy_by_state: Dict[str, int] = {}
        components_sum_by_state: Dict[str, int] = {}
        coo_5yr_by_state: Dict[str, int] = {}
        mode_data_by_state: Dict[str, dict] = {}

        for row_idx, row in group.iterrows():
            state = _safe_str(row.get("State")).upper()
            mode = _safe_str(row.get("CORE Mode")).upper()
            if not state:
                continue

            if has_listing_id:
                source_rows.append({
                    "natkey": natkey,
                    "listing_id": str(row.get("listing_id")),
                    "state": state[:3],
                    "core_mode": mode[:1],
                    "is_suppressed": _safe_bool(row.get("is_suppressed")),
                    "source_row": int(row_idx) + 2,  # header is sheet row 1
                    "data": {col: _json_safe(val) for col, val in row.items()},
                })

            driveaway_by_state[state] = _dollars_to_cents(row.get("Driveaway Price ($)"))
            base_coo_by_state[state] = _dollars_to_cents(row.get("Base COO p.a. ($)"))
            fuel_cost_by_state[state] = _dollars_to_cents(row.get("fuel_cost_pa"))
            electricity_cost_by_state[state] = _dollars_to_cents(row.get("electricity_cost_pa"))
            ctp_by_state[state] = _dollars_to_cents(row.get("ctp_pa"))
            insurance_by_state[state] = _dollars_to_cents(row.get("comprehensive_pa"))
            registration_by_state[state] = _dollars_to_cents(row.get("registration_pa"))
            ev_levy_by_state[state] = _dollars_to_cents(row.get("ruc_pa"))

            # Components sum is not a sheet column — derive it so the rating
            # engine's base_coo − components_sum reconciliation keeps working.
            components = [
                fuel_cost_by_state[state],
                electricity_cost_by_state[state],
                ctp_by_state[state],
                insurance_by_state[state],
                registration_by_state[state],
                _dollars_to_cents(row.get("maintenance_pa")),
                _dollars_to_cents(row.get("tyre_cost_pa")),
            ]
            components_sum_by_state[state] = sum(c for c in components if c) or None

            # Canonical 5yr COO: prefer Pure Cost (B), else first mode seen.
            if mode == "B" or state not in coo_5yr_by_state:
                coo_5yr_by_state[state] = _dollars_to_cents(row.get("Mode 5yr COO ($)"))

            mode_data_by_state.setdefault(state, {})
            if mode:
                mode_data = {
                    "finance_cost_pa": _safe_float(row.get("Finance Cost p.a. ($)")),
                    "resale_credit_pa": _safe_float(row.get("Resale Credit p.a. ($)")),
                    "mode_coo_pa": _safe_float(row.get("Mode COO p.a. ($)")),
                    "mode_5yr_coo": _safe_float(row.get("Mode 5yr COO ($)")),
                    "annual_co2_kg": _safe_float(row.get("Annual CO2 (kg)")),
                    "price_score": _safe_float(row.get("price_score")),
                    "emissions_score": _safe_float(row.get("emissions_score")),
                    "core_score": _safe_float(row.get("core_score")),
                    "stars": _safe_float(row.get("stars")),
                    "mode_label": _safe_str(row.get("Mode Label")),
                    "core_rating_1dp": _safe_float(row.get("core_rating_1dp")),
                    "core_rating_capped": _safe_float(row.get("core_rating_capped")),
                    "co2_cap_tier": _safe_str(row.get("co2_cap_tier")),
                    "band_name": _safe_str(row.get("band_name")),
                }
                # CO2/energy detail (21-Oct columns; constant per vehicle but
                # may vary by state — stored per state+mode, keys omitted
                # when the sheet value is missing).
                for key in (
                    "electric_share", "offgrid_share", "fuel_l100_used",
                    "co2_fuel_g_km", "co2_grid_g_km", "co2_tailpipe_pa_kg",
                ):
                    val = _safe_float(row.get(key))
                    if val is not None:
                        mode_data[key] = val
                mode_data_by_state[state][mode] = mode_data

        # ---- scalar fields from the first row --------------------------------
        battery = _safe_float(base.get("Battery (kWh)"))
        range_km = _safe_float(base.get("Range (km)"))
        maintenance_pa = _dollars_to_cents(base.get("maintenance_pa"))
        tyre_pa = _dollars_to_cents(base.get("tyre_cost_pa"))
        powertrain = map_powertrain(base.get("Fuel Type"))
        # is_suppressed is per listing; a name group can hold several listings
        # (up to 4 distinct listing_ids). The Vehicle is flagged only when
        # EVERY listing in the group is suppressed.
        group_is_suppressed = (
            all(_safe_bool(v) for v in group["is_suppressed"])
            if has_suppression else False
        )

        vehicle = Vehicle(
            brand=_safe_str(make),
            model=_safe_str(model),
            year=_safe_int(year) or 0,
            variant=_safe_str(variant),
            body_style=map_body_style(base.get("Body Type")),
            # Seats can differ between listings in one name group; the first
            # listing's value wins (pre-21-Oct sheets have no Seats column).
            num_seats=_safe_int(base.get("Seats")) or 5,
            powertrain_type=powertrain,
            fcai_category=_safe_str(base.get("fcai_category")),
            fcai_broad=_safe_str(base.get("fcai_broad")),
            energy_norm=_safe_str(base.get("Energy (norm)")),
            drive=_not_in_source(base.get("Drive")) or "",
            engine_l=_safe_float(_not_in_source(base.get("Engine (L)"))),
            battery_kwh=battery,
            driveaway_price_by_state=driveaway_by_state,
            fuel_consumption_per_100km=_safe_float(base.get("Fuel Eff (L/100km)")),
            electricity_consumption_per_100km=(
                BEV_FLAT_KWH_PER_100KM if powertrain == PowertrainType.BEV else None
            ),
            tailpipe_co2_g_per_km=_safe_float(base.get("CO2 Tailpipe (g/km)")),
            wltp_range_km=range_km,
            test_cycle=TestCycle.ADR,  # sheet carries no test-cycle column
            annual_km_default=_safe_int(base.get("km_pa_used")) or 13300,
            insurance_estimate_by_state=insurance_by_state,
            ctp_by_state=ctp_by_state,
            registration_by_state=registration_by_state,
            servicing_5yr_estimate=int(maintenance_pa * 5) if maintenance_pa else None,
            tyre_replacement_estimate=int(tyre_pa * 5) if tyre_pa else None,
            resale_value_5yr_estimate=_dollars_to_cents(base.get("resale_value_5yr")),
            total_5yr_cost_of_ownership_by_state=coo_5yr_by_state,
            fuel_cost_by_state=fuel_cost_by_state,
            electricity_cost_by_state=electricity_cost_by_state,
            ev_levy_by_state=ev_levy_by_state,
            base_coo_by_state=base_coo_by_state,
            components_sum_by_state=components_sum_by_state,
            mode_data_by_state=mode_data_by_state,
            is_scoring_outlier=_safe_bool(base.get("is_scoring_outlier")),
            scoring_version=_safe_str(base.get("scoring_version")),
            provenance={
                "dataset": "consolidated-vehicles-v6.4",
                "source_file": os.path.basename(filepath),
                "source_tab": _safe_str(base.get("source_tab")),
            },
            au_launch=_safe_str(base.get("AU Launch (Month / Year)")),
            price_type=_safe_str(base.get("Price Type")),
            research_status=_safe_str(base.get("Research Status")),
            source_name=_safe_str(base.get("Source")),
            internal_notes=_safe_str(base.get("Notes / Action for Ali")),
            source_tab=_safe_str(base.get("source_tab")),
            cost_category=_safe_str(base.get("cost_category (15-cat tables)")),
            energy_type=_safe_str(base.get("energy_type (v6.4 enum)")),
            finance_apr_pct=_safe_float(base.get("finance_apr_pct")),
            total_interest_5yr=_dollars_to_cents(base.get("total_interest_5yr")),
            finance_fees_5yr=_dollars_to_cents(base.get("finance_fees_5yr")),
            finance_cost_5yr=_dollars_to_cents(base.get("finance_cost_5yr")),
            retention_factor=_safe_float(base.get("retention_factor (L1×L2×L3)")),
            drivetrain=_safe_str(base.get("drivetrain (range basis)")),
            fuel_tank_l=_safe_float(base.get("fuel_tank_l")),
            range_battery_km=_safe_float(base.get("range_battery_km")),
            range_petrol_km=_safe_float(base.get("range_petrol_km")),
            range_total_km=_safe_float(base.get("range_total_km")),
            range_basis=_safe_str(base.get("range_basis")),
            range_ladder_step=_safe_int(base.get("range_ladder_step (Calc §2.11)")),
            range_estimated_badge=_safe_bool(base.get("range_estimated_badge")),
            range_prior_value=_safe_float(base.get("range_prior_value")),
            price_basis=_safe_str(base.get("price_basis")),
            fe_basis=_safe_str(base.get("fe_basis")),
            co2_basis=_safe_str(base.get("co2_basis")),
            assumption_fills=_safe_str(base.get("assumption_fills")),
            data_flags=_safe_str(base.get("data_flags")),
            range_research_note=_safe_str(base.get("range_research_note")),
            co2_energy_cycle_g_per_km=_safe_float(base.get("co2_energy_cycle_g_km")),
            spotlight_data=spotlights.get(spotlight_key, {}),
            transmission=_safe_str(base.get("transmission")),
            doors=_safe_int(base.get("Doors")),
            base_fuel=_safe_str(base.get("base_fuel")),
            phev_fuel_consumption_l100=_safe_float(
                base.get("phev_fuel_consumption_l100")
            ),
            energy_consumption_wh_km=_safe_float(
                base.get("energy_consumption_wh_km")
            ),
            co2_energy_cycle_basis=_safe_str(base.get("co2_energy_cycle_basis")),
            maintenance_5yr_detail=_maintenance_5yr_detail(base),
            is_suppressed=group_is_suppressed,
        )
        vehicles.append(vehicle)

    return vehicles, skipped, source_rows


def _upsert_vehicles(vehicles) -> Dict[str, int]:
    """Insert new / update existing Vehicles on (brand, model, variant, year)."""
    existing = {
        (v.brand, v.model, v.variant, v.year): v.id
        for v in Vehicle.objects.values_list("id", "brand", "model", "variant", "year", named=True)
    }

    to_create, to_update = [], []
    for veh in vehicles:
        key = (veh.brand, veh.model, veh.variant, veh.year)
        pk = existing.get(key)
        if pk is None:
            to_create.append(veh)
        else:
            veh.id = pk
            to_update.append(veh)

    for i in range(0, len(to_create), 500):
        Vehicle.objects.bulk_create(to_create[i:i + 500])
    for i in range(0, len(to_update), 500):
        Vehicle.objects.bulk_update(to_update[i:i + 500], VEHICLE_UPDATE_FIELDS, batch_size=500)

    return {"created": len(to_create), "updated": len(to_update)}


def import_consolidated_vehicles(
    filepath: str,
    clear: bool = False,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Import the Consolidated Vehicles v6.4 sheet into the Vehicle table.

    Returns {'vehicles_seen', 'created', 'updated', 'skipped', 'states',
    'modes', 'source_rows_written'}. With dry_run=True no database writes
    happen.
    """
    vehicles, skipped, source_rows = parse_consolidated_sheet(filepath)

    states = set()
    modes = set()
    for veh in vehicles:
        states.update(veh.driveaway_price_by_state.keys())
        for state_md in veh.mode_data_by_state.values():
            modes.update(state_md.keys())

    result = {
        "vehicles_seen": len(vehicles),
        "created": 0,
        "updated": 0,
        "skipped": skipped,
        "states": len(states),
        "modes": len(modes),
        "source_rows_written": 0,
    }

    if dry_run:
        return result

    if clear:
        Vehicle.objects.all().delete()
        ConsolidatedVehicleRow.objects.all().delete()

    res = _upsert_vehicles(vehicles)
    result["created"] = res["created"]
    result["updated"] = res["updated"]

    if source_rows:
        result["source_rows_written"] = _write_source_rows(source_rows)
    return result


def _write_source_rows(source_rows) -> int:
    """Replace ConsolidatedVehicleRows for the imported listings.

    Rows for any listing_id in the imported set are deleted first, then
    re-created in batches of 2000 — so re-imports stay idempotent per
    listing while unrelated listings keep their rows.
    """
    vehicle_ids = {
        (v.brand, v.model, v.variant, v.year): v.id
        for v in Vehicle.objects.values_list(
            "id", "brand", "model", "variant", "year", named=True
        )
    }
    listing_ids = {r["listing_id"] for r in source_rows}
    ConsolidatedVehicleRow.objects.filter(listing_id__in=listing_ids).delete()

    records = [
        ConsolidatedVehicleRow(
            vehicle_id=vehicle_ids.get(r["natkey"]),
            listing_id=r["listing_id"],
            state=r["state"],
            core_mode=r["core_mode"],
            is_suppressed=r["is_suppressed"],
            source_row=r["source_row"],
            data=r["data"],
        )
        for r in source_rows
    ]
    for i in range(0, len(records), 2000):
        ConsolidatedVehicleRow.objects.bulk_create(records[i:i + 2000])
    return len(records)
