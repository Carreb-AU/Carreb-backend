import os
import re
import shutil
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime, timezone

import pandas as pd
import numpy as np
from django.conf import settings
from django.db import transaction

from apps.vehicles.models import (
    CategoryCostDefault,
    DataSource,
    DepreciationBrandModifier,
    EnergyTypeModifier,
    VehicleIdentity,
    PowertrainType,
    Vehicle,
)

# Spec §3.5 modifiers.
# Insurance state modifiers are fixed below; EnergyTypeModifier and
# DepreciationBrandModifier are now models and applied at runtime.
INSURANCE_STATE_MODIFIERS = {
    'NSW': 1.178,
    'VIC': 1.510,
    'QLD': 0.932,
    'SA':  0.923,
    'WA':  0.652,
    'TAS': 0.762,
    'NT':  1.146,
    'ACT': 0.899,
}


def _get_energy_modifier(powertrain_type: str) -> Optional[EnergyTypeModifier]:
    if not powertrain_type:
        return None
    return EnergyTypeModifier.objects.filter(powertrain_type=powertrain_type).first()


def _get_brand_modifier(brand: str) -> Optional[DepreciationBrandModifier]:
    if not brand:
        return None
    return DepreciationBrandModifier.objects.filter(brand__iexact=brand).first()


def _apply_energy_modifiers(vehicle_like, default: CategoryCostDefault):
    """Apply powertrain-based multipliers to category benchmark components."""
    modifier = _get_energy_modifier(getattr(vehicle_like, 'powertrain_type', None))
    if not modifier:
        return

    state = vehicle_like._state

    def _apply(field_name: str, multiplier: float, json_field: str):
        data = getattr(vehicle_like, json_field, None) or {}
        value = data.get(state)
        if value:
            data[state] = int(round(value * multiplier))
            setattr(vehicle_like, json_field, data)

    _apply('fuel_cost_pa', modifier.fuel_cost_multiplier, 'fuel_cost_by_state')
    _apply('electricity_cost_pa', modifier.electricity_cost_multiplier, 'electricity_cost_by_state')
    _apply('registration_pa', modifier.registration_cost_multiplier, 'registration_by_state')

    # Insurance already got the state modifier; the energy multiplier is secondary.
    _apply('comprehensive_pa', modifier.insurance_cost_multiplier, 'insurance_estimate_by_state')

    # CTP is government-mandated; leave it alone by default.

    if default.servicing_5yr_estimate and modifier.servicing_cost_multiplier != 1.0:
        vehicle_like.servicing_5yr_estimate = int(round(
            default.servicing_5yr_estimate * modifier.servicing_cost_multiplier
        ))

    if default.tyre_replacement_estimate and modifier.tyre_cost_multiplier != 1.0:
        vehicle_like.tyre_replacement_estimate = int(round(
            default.tyre_replacement_estimate * modifier.tyre_cost_multiplier
        ))


def _get_resale_modifiers(powertrain_type: str, brand: str) -> tuple[float, float]:
    """Return (energy_multiplier, brand_multiplier) for resale/retention."""
    energy_mod = _get_energy_modifier(powertrain_type)
    brand_mod = _get_brand_modifier(brand)
    energy_mult = energy_mod.resale_value_multiplier if energy_mod else 1.0
    brand_mult = brand_mod.resale_value_multiplier if brand_mod else 1.0
    return energy_mult, brand_mult


def _get_retention_modifiers(powertrain_type: str, brand: str) -> tuple[float, float]:
    """Return (energy_multiplier, brand_multiplier) for retention rate."""
    energy_mod = _get_energy_modifier(powertrain_type)
    brand_mod = _get_brand_modifier(brand)
    energy_mult = energy_mod.retention_multiplier if energy_mod else 1.0
    brand_mult = brand_mod.retention_multiplier if brand_mod else 1.0
    return energy_mult, brand_mult


def _get_manual_source() -> Optional[DataSource]:
    """Return the registered S-CARREB-MANUAL source, creating it if absent."""
    source, _ = DataSource.objects.get_or_create(
        code='S-CARREB-MANUAL',
        defaults={
            'name': 'Carreb Manual Enrichment',
            'url': '',
            'dataset_type': 'manual',
        },
    )
    return source


class VehicleLike:
    """
    Duck-typed stand-in for Vehicle used when a GVG record is selected as the
    user's current vehicle. It exposes the fields calculate_core_rating expects.
    """
    def __init__(self, record: VehicleIdentity, state: str):
        self._record = record
        self._state = state.upper()
        self.id = record.id
        self.brand = record.make
        self.model = record.model
        self.year = record.year
        self.variant = record.variant
        self.body_style = record.body_style
        self.powertrain_type = record.powertrain_type
        self.fcai_category = record.fcai_category
        self.fcai_broad = record.fcai_broad
        self.energy_norm = ''
        self.drive = ''
        self.engine_l = record.engine_l
        self.battery_kwh = record.battery_kwh
        self.num_seats = record.num_seats or 5
        self.ancap_safety_rating = None
        self.annual_km_default = 13300
        self.image_url = record.image_url or ''
        self.driveaway_price_by_state = {}
        self.servicing_5yr_estimate = record.servicing_5yr_estimate
        self.tyre_replacement_estimate = record.tyre_replacement_estimate
        self.resale_value_5yr_estimate = record.resale_value_5yr_estimate
        self.is_scoring_outlier = False
        self.scoring_version = 'gvg-v1'
        self.provenance = record.provenance or {
            'source': 'green_vehicle_guide_record',
            'source_dataset': record.source_dataset,
            'record_id': str(record.id),
        }

        # Apply admin-level manual enrichment if present.
        self._apply_manual_enrichment()

        # Consumption / emissions
        self.fuel_consumption_per_100km = record.fuel_consumption_combined_l_100km
        # GVG gives Wh/km; CORE expects kWh/100km -> divide by 10.
        self.electricity_consumption_per_100km = (
            record.electricity_consumption_wh_per_km / 10.0
            if record.electricity_consumption_wh_per_km else None
        )
        self.tailpipe_co2_g_per_km = record.tailpipe_co2_g_per_km
        self.wltp_range_km = record.electric_range_km
        self.test_cycle = record.test_cycle or 'ADR'

        # Costs by state. GVG records do not store every field that a full Carreb
        # Vehicle has, so fall back to empty dicts / None and let defaults fill the gaps.
        self.ctp_by_state = record.ctp_by_state or {}
        self.insurance_estimate_by_state = record.insurance_estimate_by_state or {}
        self.registration_by_state = record.registration_by_state or {}
        self.fuel_cost_by_state = getattr(record, 'fuel_cost_by_state', None) or {}
        self.electricity_cost_by_state = getattr(record, 'electricity_cost_by_state', None) or {}
        self.ev_levy_by_state = getattr(record, 'ev_levy_by_state', None) or {}
        self.base_coo_by_state = record.total_5yr_cost_of_ownership_by_state or {}
        self.components_sum_by_state = record.total_5yr_cost_of_ownership_by_state or {}
        self.total_5yr_cost_of_ownership_by_state = record.total_5yr_cost_of_ownership_by_state or {}
        self.mode_data_by_state = getattr(record, 'mode_data_by_state', None) or {}

        # Do not use GVG's own AnnualFuelCost or driveaway estimate as the
        # displayed Carreb value. The Carreb model uses consumption × state fuel
        # price × km p.a. and its own driveaway data. Category defaults fill any
        # gaps until state fuel-price and depreciation modifier tables are ready.

        self._apply_defaults_if_missing()

    def _state_value(self, d):
        return d.get(self._state)

    def _apply_manual_enrichment(self):
        """Apply admin-curated ManualVehicleEnrichment values and badge them."""
        enrichment = getattr(self._record, 'manual_enrichment', None)
        if not enrichment:
            return

        manual_source = _get_manual_source()
        manual_badge = {
            'source_code': 'S-CARREB-MANUAL',
            'source_name': 'Carreb Manual Enrichment',
            'source_id': str(manual_source.id) if manual_source else None,
        }

        if enrichment.engine_l is not None and self.engine_l is None:
            self.engine_l = enrichment.engine_l
            self.provenance.setdefault('engine_l', manual_badge)

        if enrichment.ancap_safety_rating is not None and self.ancap_safety_rating is None:
            self.ancap_safety_rating = enrichment.ancap_safety_rating
            self.provenance.setdefault('ancap_safety_rating', manual_badge)

        if enrichment.image_url and not self.image_url:
            self.image_url = enrichment.image_url
            self.provenance.setdefault('image_url', manual_badge)

        if enrichment.driveaway_price_estimate is not None:
            self.driveaway_price_by_state[self._state] = enrichment.driveaway_price_estimate
            self.provenance.setdefault('driveaway_price', manual_badge)

        if enrichment.resale_value_5yr_estimate is not None and self.resale_value_5yr_estimate is None:
            self.resale_value_5yr_estimate = enrichment.resale_value_5yr_estimate
            self.provenance.setdefault('resale_value_5yr_estimate', manual_badge)

    def _apply_defaults_if_missing(self):
        """Pull category defaults for the chosen state if cost fields are empty.

        The client spec calls for CategoryBenchmark × modifiers.
        Insurance state modifiers and energy-type modifiers are applied here.
        Brand depreciation modifiers are applied at resale/retention time.
        """
        if not self.fcai_category:
            return
        default = CategoryCostDefault.objects.filter(
            fcai_category=self.fcai_category,
            state=self._state
        ).first()
        if not default:
            return

        self.annual_km_default = default.annual_km or 13300

        if self._state and not self._state_value(self.ctp_by_state):
            self.ctp_by_state[self._state] = default.ctp_pa
        if self._state and not self._state_value(self.insurance_estimate_by_state):
            base = default.comprehensive_pa or 0
            modifier = INSURANCE_STATE_MODIFIERS.get(self._state, 1.0)
            self.insurance_estimate_by_state[self._state] = int(round(base * modifier)) if base else None
        if self._state and not self._state_value(self.registration_by_state):
            self.registration_by_state[self._state] = default.registration_pa
        if self._state and not self._state_value(self.fuel_cost_by_state):
            self.fuel_cost_by_state[self._state] = default.fuel_cost_pa

        # Apply powertrain-based multipliers on top of the category benchmark.
        _apply_energy_modifiers(self, default)
        if self._state and not self._state_value(self.electricity_cost_by_state):
            self.electricity_cost_by_state[self._state] = default.electricity_cost_pa
        if self._state and not self._state_value(self.ev_levy_by_state):
            self.ev_levy_by_state[self._state] = default.ev_levy_pa

        if self.servicing_5yr_estimate is None:
            self.servicing_5yr_estimate = default.servicing_5yr_estimate
        if self.tyre_replacement_estimate is None:
            self.tyre_replacement_estimate = default.tyre_replacement_estimate


def build_vehicle_like_from_gvg(record: VehicleIdentity, state: str) -> VehicleLike:
    return VehicleLike(record, state)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _safe_float(val):
    if val is None or pd.isna(val) or val == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    if val is None or pd.isna(val) or val == '':
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _safe_str(val):
    if val is None or pd.isna(val):
        return ''
    return str(val).strip()


def _plain_dict_from_row(row: pd.Series) -> dict:
    """Convert a pandas row to JSON-safe plain Python types."""
    out = {}
    for k, v in row.items():
        if pd.isna(v):
            continue
        if isinstance(v, (np.integer, np.floating)):
            v = v.item()
        out[k] = v
    return out


def _dollars_to_cents(val):
    """Convert dollar values (float or int) to whole cents."""
    f = _safe_float(val)
    if f is None:
        return None
    return int(round(f * 100))


def _parse_engine_displacement(val):
    """GVG stores engine displacement as string like '2.4' or numeric."""
    return _safe_float(val)


def map_powertrain(fuel_type_raw: str) -> str:
    """Map GVG fuel type strings to Carreb PowertrainType."""
    if not fuel_type_raw:
        return PowertrainType.PETROL
    ft = str(fuel_type_raw).lower()

    if 'plug-in electric' in ft or 'phev' in ft:
        return PowertrainType.PHEV
    if 'pure electric' in ft or ft == 'electric':
        return PowertrainType.BEV
    if 'hydrogen' in ft or 'fcev' in ft:
        return PowertrainType.FCEV
    if 'electric/petrol' in ft or 'electric/diesel' in ft:
        return PowertrainType.HYBRID
    if 'mild hybrid' in ft or 'mild' in ft:
        return PowertrainType.MILD_HYBRID
    if 'hybrid' in ft or 'hev' in ft:
        return PowertrainType.HYBRID
    if 'diesel' in ft:
        return PowertrainType.DIESEL
    if 'petrol' in ft or 'lpg' in ft or 'cng' in ft:
        return PowertrainType.PETROL

    return PowertrainType.PETROL


def map_body_style(body_style_raw: str) -> str:
    """Normalise body style into Carreb vocabulary."""
    if not body_style_raw:
        return ''
    bs = str(body_style_raw).lower().strip()
    if bs in ('hatch', 'hatchback'):
        return 'hatchback'
    if bs in ('sedan', 'saloon'):
        return 'sedan'
    if bs in ('wagon', 'estate', 'tourer', 'sportswagon'):
        return 'wagon'
    if bs in ('suv', 'crossover'):
        return 'suv'
    if bs in ('ute', 'utility', 'pick-up', 'pickup'):
        return 'ute'
    if bs in ('van', 'minivan', 'passenger van'):
        return 'van'
    if bs in ('cab-chassis', 'cab chassis', 'cabchassis'):
        return 'cab chassis'
    if bs in ('coupe', 'coupe sport'):
        return 'coupe'
    if bs in ('convertible', 'cabriolet', 'roadster'):
        return 'convertible'
    if bs in ('people mover', 'people-mover', 'minibus', 'light bus'):
        return 'people mover'
    return bs


def infer_fcai_category(body_style: str, num_seats: Optional[int], model: str = '') -> tuple:
    """
    Infer (fcai_category, fcai_broad) from body style and seats.
    Returns broad category names consistent with the Carreb workbook.
    """
    bs = (body_style or '').lower().strip()
    seats = num_seats or 5

    # People movers / vans
    if bs in ('people mover', 'light bus'):
        return 'People-Mover', 'Passenger Cars'
    if bs == 'van':
        return 'Van', 'Light Commercial'
    if bs in ('ute', 'cab chassis'):
        return 'Ute', 'Light Commercial'

    # Sports cars (heuristic by body style)
    if bs in ('coupe', 'convertible'):
        return 'Sports', 'Passenger Cars'

    # SUVs by seating capacity
    if bs == 'suv':
        if seats >= 7:
            return 'SUV-Large', 'SUV'
        if seats >= 5:
            return 'SUV-Medium', 'SUV'
        return 'SUV-Small', 'SUV'

    # Passenger car sizing is hard without dimensions. Use a few model-name hints.
    model_lower = (model or '').lower()
    micro_models = ('picanto', 'swift', 'yaris', 'fabia', 'rio', 'jazz', 'mazda2', 'corolla', 'i30', 'cerato', 'golf')
    light_models = ('accent', 'astra', 'focus', 'cruze', '3 series', 'c-class', 'a4')
    large_models = ('commodore', 'falcon', 'camry', 'aurion', '5 series', 'e-class', 'a6')

    # Default to Small/Medium/Large by seats is crude but serviceable.
    # Prefer Medium for sedans/wagons with 5 seats.
    if bs in ('sedan', 'wagon', 'hatchback'):
        if any(m in model_lower for m in micro_models):
            return 'Light', 'Passenger Cars'
        if any(m in model_lower for m in large_models):
            return 'Large', 'Passenger Cars'
        return 'Medium', 'Passenger Cars'

    return 'Medium', 'Passenger Cars'


def estimate_co2_from_fuel_and_consumption(fuel_type: str, consumption_l_100km: Optional[float]) -> Optional[float]:
    """
    Rough CO2 g/km estimate for older vehicles that did not publish CO2.
    Factors: petrol ~2.31 kg CO2/L, diesel ~2.68 kg CO2/L, LPG ~1.51 kg CO2/L.
    Convert to g/km: (L/100km * factor) / 100 -> g/km.
    """
    if consumption_l_100km is None:
        return None
    ft = (fuel_type or '').lower()
    if 'diesel' in ft:
        factor = 2680.0
    elif 'lpg' in ft or 'cng' in ft:
        factor = 1510.0
    else:
        factor = 2310.0
    return round((consumption_l_100km * factor) / 100.0, 1)


# ---------------------------------------------------------------------------
# Cost defaults
# ---------------------------------------------------------------------------

def compute_category_cost_defaults(filepath: str) -> Dict[tuple, dict]:
    """
    Read COO_Component_Breakdown and return median cost components
    per (fcai_category, state).
    """
    df = pd.read_excel(filepath, sheet_name='COO_Component_Breakdown')

    numeric_cols = [
        'km_pa_used', 'ctp_pa', 'comprehensive_pa', 'registration_pa',
        'maintenance_pa', 'tyre_cost_pa', 'fuel_cost_pa',
        'electricity_cost_pa', 'ev_levy_pa', 'components_sum_pa'
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    grouped = {}
    for (fcai_category, state), group in df.groupby(['fcai_category', 'State']):
        state = str(state).upper().strip()
        if not state:
            continue

        def med(col):
            s = group[col].dropna()
            return float(s.median()) if not s.empty else None

        grouped[(fcai_category, state)] = {
            'fcai_category': fcai_category,
            'fcai_broad': _safe_str(group['fcai_broad'].dropna().iloc[0]) if not group['fcai_broad'].dropna().empty else '',
            'annual_km': _safe_int(group['km_pa_used'].dropna().iloc[0]) if not group['km_pa_used'].dropna().empty else 13300,
            'ctp_pa': _dollars_to_cents(med('ctp_pa')),
            'comprehensive_pa': _dollars_to_cents(med('comprehensive_pa')),
            'registration_pa': _dollars_to_cents(med('registration_pa')),
            'maintenance_pa': _dollars_to_cents(med('maintenance_pa')),
            'tyre_cost_pa': _dollars_to_cents(med('tyre_cost_pa')),
            'fuel_cost_pa': _dollars_to_cents(med('fuel_cost_pa')),
            'electricity_cost_pa': _dollars_to_cents(med('electricity_cost_pa')),
            'ev_levy_pa': _dollars_to_cents(med('ev_levy_pa')),
            'components_sum_pa': _dollars_to_cents(med('components_sum_pa')),
        }
    return grouped


def import_category_cost_defaults(filepath: str, clear: bool = False) -> int:
    """Populate CategoryCostDefault from the Carreb workbook."""
    defaults = compute_category_cost_defaults(filepath)

    if clear:
        CategoryCostDefault.objects.all().delete()

    created = 0
    for key, data in defaults.items():
        defaults_for_5yr = {
            'servicing_5yr_estimate': data['maintenance_pa'] * 5 if data['maintenance_pa'] else None,
            'tyre_replacement_estimate': data['tyre_cost_pa'] * 5 if data['tyre_cost_pa'] else None,
        }
        obj, was_created = CategoryCostDefault.objects.update_or_create(
            fcai_category=data['fcai_category'],
            state=key[1],
            defaults={
                'fcai_broad': data['fcai_broad'],
                'annual_km': data['annual_km'],
                'ctp_pa': data['ctp_pa'],
                'comprehensive_pa': data['comprehensive_pa'],
                'registration_pa': data['registration_pa'],
                'maintenance_pa': data['maintenance_pa'],
                'tyre_cost_pa': data['tyre_cost_pa'],
                'fuel_cost_pa': data['fuel_cost_pa'],
                'electricity_cost_pa': data['electricity_cost_pa'],
                'ev_levy_pa': data['ev_levy_pa'],
                'components_sum_pa': data['components_sum_pa'],
                **defaults_for_5yr,
            }
        )
        if was_created:
            created += 1
    return created


def apply_cost_defaults(record: VehicleIdentity, state: str) -> None:
    """Mutate the record's cost fields from CategoryCostDefault if blank."""
    default = CategoryCostDefault.objects.filter(
        fcai_category=record.fcai_category,
        state=state.upper()
    ).first()

    if not default:
        return

    if not record.ctp_by_state:
        record.ctp_by_state = {}
    if not record.insurance_estimate_by_state:
        record.insurance_estimate_by_state = {}
    if not record.registration_by_state:
        record.registration_by_state = {}
    if not record.total_5yr_cost_of_ownership_by_state:
        record.total_5yr_cost_of_ownership_by_state = {}

    record.ctp_by_state[state] = default.ctp_pa
    base_insurance = default.comprehensive_pa or 0
    modifier = INSURANCE_STATE_MODIFIERS.get(state, 1.0)
    record.insurance_estimate_by_state[state] = int(round(base_insurance * modifier)) if base_insurance else None
    record.registration_by_state[state] = default.registration_pa
    record.fuel_cost_by_state = record.fuel_cost_by_state or {}
    record.fuel_cost_by_state[state] = default.fuel_cost_pa
    record.electricity_cost_by_state = record.electricity_cost_by_state or {}
    record.electricity_cost_by_state[state] = default.electricity_cost_pa
    record.ev_levy_by_state = record.ev_levy_by_state or {}
    record.ev_levy_by_state[state] = default.ev_levy_pa

    if record.servicing_5yr_estimate is None:
        record.servicing_5yr_estimate = default.servicing_5yr_estimate
    if record.tyre_replacement_estimate is None:
        record.tyre_replacement_estimate = default.tyre_replacement_estimate


# ---------------------------------------------------------------------------
# XLSX import (2004-2025)
# ---------------------------------------------------------------------------

def _looks_like_corrupt_row(row: pd.Series) -> bool:
    """Detect rows where Variant contains a comma shifting columns (numeric FuelType)."""
    fuel = _safe_str(row.get('FuelType'))
    if re.match(r'^-?\d+(\.\d+)?$', fuel):
        return True
    return False


def import_gvg_xlsx(filepath: str, source: Optional[DataSource] = None, clear: bool = False) -> Dict[str, int]:
    df = pd.read_excel(filepath, sheet_name='Vehicles 2004-2025')

    if clear:
        VehicleIdentity.objects.filter(source_dataset='GVG-CURRENT').delete()

    created = 0
    skipped = 0
    records = []

    for _, row in df.iterrows():
        if _looks_like_corrupt_row(row):
            skipped += 1
            continue

        make = _safe_str(row.get('Make'))
        model = _safe_str(row.get('Model'))
        year = _safe_int(row.get('ModelReleaseYear'))

        if not make or not model or year is None:
            skipped += 1
            continue

        variant = _safe_str(row.get('Variant'))
        body_style = map_body_style(row.get('BodyStyle'))
        num_seats = _safe_int(row.get('SeatingCapacity'))
        fcai_category, fcai_broad = infer_fcai_category(body_style, num_seats, model)
        fuel_type_raw = _safe_str(row.get('FuelType'))
        powertrain = map_powertrain(fuel_type_raw)

        test_cycle = _safe_str(row.get('Test Cycle')) or 'ADR'
        record = VehicleIdentity(
            source=source,
            make=make,
            model=model,
            year=year,
            variant=variant,
            body_style=body_style,
            fcai_category=fcai_category,
            fcai_broad=fcai_broad,
            powertrain_type=powertrain,
            fuel_type_raw=fuel_type_raw,
            engine_l=_parse_engine_displacement(row.get('EngineDisplacement')),
            num_seats=num_seats,
            transmission=_safe_str(row.get('TransmissionTypeDescription')),
            fuel_consumption_combined_l_100km=_safe_float(row.get('FuelConsumptionCombined')),
            fuel_consumption_urban_l_100km=_safe_float(row.get('FuelConsumptionUrban')),
            fuel_consumption_extra_urban_l_100km=_safe_float(row.get('FuelConsumptionExtraUrban')),
            electricity_consumption_wh_per_km=_safe_float(row.get('EnergyConsumptionWhkm')),
            electric_range_km=_safe_float(row.get('ElectricRangeKm')),
            tailpipe_co2_g_per_km=_safe_float(row.get('CO2EmissionsCombined')),
            annual_fuel_cost=_dollars_to_cents(row.get('AnnualFuelCost')),
            is_current_model=str(row.get('IsCurrentModel')).lower().strip() == 'yes' if pd.notna(row.get('IsCurrentModel')) else None,
            model_end_year=_safe_int(row.get('ModelEndYear')),
            test_cycle=test_cycle,
            source_dataset='GVG-CURRENT',
            raw_data=_plain_dict_from_row(row),
            provenance=_build_record_provenance(source, test_cycle),
            search_text=' '.join(p for p in [str(year), make, model, variant] if p).lower(),
        )

        records.append(record)
        if len(records) >= 1000:
            VehicleIdentity.objects.bulk_create(records, batch_size=1000)
            created += len(records)
            records = []

    if records:
        VehicleIdentity.objects.bulk_create(records, batch_size=1000)
        created += len(records)

    return {'created': created, 'skipped': skipped}


# ---------------------------------------------------------------------------
# CSV import (1986-2003)
# ---------------------------------------------------------------------------

def import_old_fuel_consumption_csv(filepath: str, source: Optional[DataSource] = None, clear: bool = False) -> Dict[str, int]:
    df = pd.read_csv(filepath)

    if clear:
        VehicleIdentity.objects.filter(source_dataset='GVG-OLDER-8603').delete()

    created = 0
    skipped = 0
    records = []

    for _, row in df.iterrows():
        make = _safe_str(row.get('MANUFACTURER'))
        model = _safe_str(row.get('MODEL'))
        year = _safe_int(row.get('YEAR'))

        if not make or not model or year is None:
            skipped += 1
            continue

        body_style = map_body_style(row.get('BODY_STYLE'))
        num_seats = _safe_int(row.get('SEATING_CAPACITY'))
        fcai_category, fcai_broad = infer_fcai_category(body_style, num_seats, model)
        fuel_type_raw = _safe_str(row.get('FUEL'))
        powertrain = map_powertrain(fuel_type_raw)

        city = _safe_float(row.get('CITY_CYCLE'))
        highway = _safe_float(row.get('HIGHWAY_CYCLE'))
        adr8101 = _safe_float(row.get('ADR8101_CYCLE'))

        if adr8101 is not None:
            combined = adr8101
        elif city is not None and highway is not None:
            combined = round((city + highway) / 2.0, 1)
        else:
            combined = city or highway

        co2 = estimate_co2_from_fuel_and_consumption(fuel_type_raw, combined)

        test_cycle = 'ADR'
        record = VehicleIdentity(
            source=source,
            make=make,
            model=model,
            year=year,
            variant='',
            body_style=body_style,
            fcai_category=fcai_category,
            fcai_broad=fcai_broad,
            powertrain_type=powertrain,
            fuel_type_raw=fuel_type_raw,
            engine_l=_safe_float(row.get('ENGINE_DISPLACEMENT')),
            num_seats=num_seats,
            transmission=_safe_str(row.get('TRANSMISSION')),
            fuel_consumption_combined_l_100km=combined,
            fuel_consumption_urban_l_100km=city,
            fuel_consumption_extra_urban_l_100km=highway,
            tailpipe_co2_g_per_km=co2,
            test_cycle=test_cycle,
            source_dataset='GVG-OLDER-8603',
            raw_data=_plain_dict_from_row(row),
            provenance=_build_record_provenance(source, test_cycle),
            search_text=' '.join(p for p in [str(year), make, model] if p).lower(),
        )

        records.append(record)
        if len(records) >= 1000:
            VehicleIdentity.objects.bulk_create(records, batch_size=1000)
            created += len(records)
            records = []

    if records:
        VehicleIdentity.objects.bulk_create(records, batch_size=1000)
        created += len(records)

    return {'created': created, 'skipped': skipped}


# ---------------------------------------------------------------------------
# Orchestration helpers
# ---------------------------------------------------------------------------

def _archive_source_file(source_path: str, code: str) -> str:
    """Copy a source file into the media archive and return the relative path.

    The archived file is named by source code (e.g. S-GVG-CURRENT.xlsx) so each
    re-import overwrites the prior archive for that source. Returns the path
    relative to MEDIA_ROOT suitable for DataSource.archived_file.
    """
    if not source_path or not os.path.isfile(source_path):
        return ''

    ext = os.path.splitext(source_path)[1].lower()
    archive_dir = os.path.join(settings.MEDIA_ROOT, 'data', 'source_archives')
    os.makedirs(archive_dir, exist_ok=True)

    archive_name = f"{code}{ext}"
    archive_path = os.path.join(archive_dir, archive_name)
    shutil.copy2(source_path, archive_path)

    return f"data/source_archives/{archive_name}"


class SourceArchiveError(ValueError):
    """Raised when a required source file cannot be archived."""


def create_or_update_datasource(
    code: str,
    name: str,
    url: str,
    dataset_type: str,
    archived_path: str = '',
    source_file_path: str = '',
) -> DataSource:
    """Register or update a DataSource and archive the source file.

    Raises SourceArchiveError if a source_file_path is supplied but the file
    is missing or cannot be archived. A job with no registered active source
    archive refuses to run (Spec §5 / Decision Note 3).
    """
    archived_file = archived_path
    if source_file_path:
        archived_file = _archive_source_file(source_file_path, code)
        if not archived_file:
            raise SourceArchiveError(
                f"Source archive is required for {code} but "
                f"{source_file_path!r} was missing or could not be copied."
            )

    defaults = {
        'name': name,
        'url': url,
        'dataset_type': dataset_type,
        'retrieved_at': datetime.now(timezone.utc),
    }
    if archived_file:
        defaults['archived_file'] = archived_file

    source, _ = DataSource.objects.update_or_create(
        code=code,
        defaults=defaults
    )

    if source_file_path and not source.archived_file:
        raise SourceArchiveError(
            f"DataSource {code} was saved without an archived_file. "
            f"The source file must be persisted before import can proceed."
        )

    return source


def _build_record_provenance(source: Optional[DataSource], test_cycle: str) -> dict:
    """Return a citation-ready provenance block for a GVG record."""
    if not source:
        return {}
    return {
        "source_id": str(source.id),
        "source_code": source.code,
        "source_name": source.name,
        "source_url": source.url,
        "retrieved_at": source.retrieved_at.isoformat() if source.retrieved_at else None,
        "archived_file": source.archived_file.name if source.archived_file else None,
        "dataset_type": source.dataset_type,
        "test_cycle": test_cycle,
    }


def import_all(
    workbook_path: str,
    gvg_xlsx_path: str,
    old_csv_path: str,
    clear: bool = False
) -> Dict[str, dict]:
    """Import category defaults + both GVG datasets in one pass."""
    results = {}

    current_source = create_or_update_datasource(
        code='S-GVG-CURRENT',
        name='Green Vehicle Guide — Vehicles 2004-2025',
        url='https://greenvehicleguide.gov.au',
        dataset_type='xlsx',
        source_file_path=gvg_xlsx_path,
    )
    older_source = create_or_update_datasource(
        code='S-GVG-OLDER-8603',
        name='Fuel Consumption Guide 1986-2003',
        url='https://greenvehicleguide.gov.au',
        dataset_type='csv',
        source_file_path=old_csv_path,
    )

    results['category_defaults'] = import_category_cost_defaults(workbook_path, clear=clear)
    results['gvg_current'] = import_gvg_xlsx(gvg_xlsx_path, source=current_source, clear=clear)
    results['gvg_older'] = import_old_fuel_consumption_csv(old_csv_path, source=older_source, clear=clear)

    return results
