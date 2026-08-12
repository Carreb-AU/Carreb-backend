import os
import re
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import datetime, timezone

import pandas as pd
import numpy as np
from django.db import transaction

from apps.vehicles.models import (
    CategoryCostDefault,
    DataSource,
    GreenVehicleGuideRecord,
    PowertrainType,
    Vehicle,
)


class VehicleLike:
    """
    Duck-typed stand-in for Vehicle used when a GVG record is selected as the
    user's current vehicle. It exposes the fields calculate_core_rating expects.
    """
    def __init__(self, record: GreenVehicleGuideRecord, state: str):
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
        self.image_url = ''
        self.driveaway_price_by_state = {}
        self.servicing_5yr_estimate = record.servicing_5yr_estimate
        self.tyre_replacement_estimate = record.tyre_replacement_estimate
        self.resale_value_5yr_estimate = record.resale_value_5yr_estimate
        self.is_scoring_outlier = False
        self.scoring_version = 'gvg-v1'
        self.provenance = {
            'source': 'green_vehicle_guide_record',
            'source_dataset': record.source_dataset,
            'record_id': str(record.id),
        }

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

        # Costs by state
        self.ctp_by_state = record.ctp_by_state or {}
        self.insurance_estimate_by_state = record.insurance_estimate_by_state or {}
        self.registration_by_state = record.registration_by_state or {}
        self.fuel_cost_by_state = record.fuel_cost_by_state or {}
        self.electricity_cost_by_state = record.electricity_cost_by_state or {}
        self.ev_levy_by_state = record.ev_levy_by_state or {}
        self.base_coo_by_state = record.total_5yr_cost_of_ownership_by_state or {}
        self.components_sum_by_state = record.total_5yr_cost_of_ownership_by_state or {}
        self.total_5yr_cost_of_ownership_by_state = record.total_5yr_cost_of_ownership_by_state or {}
        self.mode_data_by_state = {}

        self._apply_defaults_if_missing()

    def _state_value(self, d):
        return d.get(self._state)

    def _apply_defaults_if_missing(self):
        """Pull category defaults for the chosen state if cost fields are empty."""
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
            self.insurance_estimate_by_state[self._state] = default.comprehensive_pa
        if self._state and not self._state_value(self.registration_by_state):
            self.registration_by_state[self._state] = default.registration_pa
        if self._state and not self._state_value(self.fuel_cost_by_state):
            self.fuel_cost_by_state[self._state] = default.fuel_cost_pa
        if self._state and not self._state_value(self.electricity_cost_by_state):
            self.electricity_cost_by_state[self._state] = default.electricity_cost_pa
        if self._state and not self._state_value(self.ev_levy_by_state):
            self.ev_levy_by_state[self._state] = default.ev_levy_pa

        if self.servicing_5yr_estimate is None:
            self.servicing_5yr_estimate = default.servicing_5yr_estimate
        if self.tyre_replacement_estimate is None:
            self.tyre_replacement_estimate = default.tyre_replacement_estimate


def build_vehicle_like_from_gvg(record: GreenVehicleGuideRecord, state: str) -> VehicleLike:
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


def apply_cost_defaults(record: GreenVehicleGuideRecord, state: str) -> None:
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
    record.insurance_estimate_by_state[state] = default.comprehensive_pa
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
        GreenVehicleGuideRecord.objects.filter(source_dataset='GVG-CURRENT').delete()

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

        record = GreenVehicleGuideRecord(
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
            test_cycle=_safe_str(row.get('Test Cycle')) or 'ADR',
            source_dataset='GVG-CURRENT',
            raw_data=_plain_dict_from_row(row),
            search_text=' '.join(p for p in [str(year), make, model, variant] if p).lower(),
        )

        records.append(record)
        if len(records) >= 1000:
            GreenVehicleGuideRecord.objects.bulk_create(records, batch_size=1000)
            created += len(records)
            records = []

    if records:
        GreenVehicleGuideRecord.objects.bulk_create(records, batch_size=1000)
        created += len(records)

    return {'created': created, 'skipped': skipped}


# ---------------------------------------------------------------------------
# CSV import (1986-2003)
# ---------------------------------------------------------------------------

def import_old_fuel_consumption_csv(filepath: str, source: Optional[DataSource] = None, clear: bool = False) -> Dict[str, int]:
    df = pd.read_csv(filepath)

    if clear:
        GreenVehicleGuideRecord.objects.filter(source_dataset='GVG-OLDER-8603').delete()

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

        record = GreenVehicleGuideRecord(
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
            test_cycle='ADR',
            source_dataset='GVG-OLDER-8603',
            raw_data=_plain_dict_from_row(row),
            search_text=' '.join(p for p in [str(year), make, model] if p).lower(),
        )

        records.append(record)
        if len(records) >= 1000:
            GreenVehicleGuideRecord.objects.bulk_create(records, batch_size=1000)
            created += len(records)
            records = []

    if records:
        GreenVehicleGuideRecord.objects.bulk_create(records, batch_size=1000)
        created += len(records)

    return {'created': created, 'skipped': skipped}


# ---------------------------------------------------------------------------
# Orchestration helpers
# ---------------------------------------------------------------------------

def create_or_update_datasource(code: str, name: str, url: str, dataset_type: str, archived_path: str = '') -> DataSource:
    defaults = {
        'name': name,
        'url': url,
        'dataset_type': dataset_type,
        'retrieved_at': datetime.now(timezone.utc),
    }
    if archived_path:
        defaults['archived_file'] = archived_path

    source, _ = DataSource.objects.update_or_create(
        code=code,
        defaults=defaults
    )
    return source


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
    )
    older_source = create_or_update_datasource(
        code='S-GVG-OLDER-8603',
        name='Fuel Consumption Guide 1986-2003',
        url='https://greenvehicleguide.gov.au',
        dataset_type='csv',
    )

    results['category_defaults'] = import_category_cost_defaults(workbook_path, clear=clear)
    results['gvg_current'] = import_gvg_xlsx(gvg_xlsx_path, source=current_source, clear=clear)
    results['gvg_older'] = import_old_fuel_consumption_csv(old_csv_path, source=older_source, clear=clear)

    return results
