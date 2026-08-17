import pandas as pd
import numpy as np
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.vehicles.models import Vehicle, PowertrainType, TestCycle

class Command(BaseCommand):
    help = 'ETL script to import Carreb Vehicle Data into the single Vehicle model with nested JSON fields'

    def add_arguments(self, parser):
        parser.add_argument('filepath', type=str, help='Path to Excel file')
        parser.add_argument('--clear', action='store_true', help='Clear existing Vehicle data before import')

    def _safe_float(self, val):
        if pd.isna(val) or val == '':
            return None
        try:
            return float(val)
        except:
            return None

    def _safe_int(self, val):
        if pd.isna(val) or val == '':
            return None
        try:
            return int(float(val))
        except:
            return None
            
    def _safe_str(self, val):
        if pd.isna(val):
            return ''
        return str(val).strip()
        
    def _safe_bool(self, val):
        if pd.isna(val):
            return False
        return bool(val)

    # Workbook header / metadata rows that were previously imported as junk
    # vehicles.  Real vehicle makes are short names (e.g. "Toyota", "Land Rover");
    # they never contain underscores or worksheet metadata keywords.
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

    def _is_junk_make(self, make):
        if pd.isna(make):
            return True
        text = str(make).strip().lower()
        if not text:
            return True
        return any(kw in text for kw in self._JUNK_MAKE_KEYWORDS)

    def _filter_vehicle_rows(self, df):
        """Drop rows that are clearly workbook metadata rather than vehicles."""
        if df is None or df.empty:
            return df
        mask = df["Make"].apply(lambda m: not self._is_junk_make(m))
        dropped = len(df) - mask.sum()
        if dropped:
            self.stdout.write(self.style.WARNING(f"Dropped {dropped} non-vehicle rows"))
        return df[mask].copy()

    def _dollars_to_cents(self, val):
        """Convert a dollar value to whole cents for storage."""
        f = self._safe_float(val)
        if f is None:
            return None
        return int(round(f * 100))

    def map_powertrain(self, fuel_type):
        if pd.isna(fuel_type):
            return PowertrainType.PETROL
        ft = str(fuel_type).lower()
        if 'petrol' in ft: return PowertrainType.PETROL
        if 'diesel' in ft: return PowertrainType.DIESEL
        if 'mild' in ft: return PowertrainType.MILD_HYBRID
        if 'phev' in ft: return PowertrainType.PHEV
        if 'hev' in ft or 'hybrid' in ft: return PowertrainType.HYBRID
        if 'bev' in ft or 'electric' in ft: return PowertrainType.BEV
        if 'fcev' in ft or 'hydrogen' in ft: return PowertrainType.FCEV
        return PowertrainType.PETROL

    @transaction.atomic
    def handle(self, *args, **options):
        filepath = options['filepath']
        
        if options['clear']:
            self.stdout.write("Clearing existing Vehicle data...")
            Vehicle.objects.all().delete()
            
        self.stdout.write("Loading workbook (this might take a minute)...")
        try:
            df_data = pd.read_excel(filepath, sheet_name='v6.3.4 Data')
            df_coo = pd.read_excel(filepath, sheet_name='COO_Component_Breakdown')
        except Exception as e:
            self.stderr.write(f"Error reading Excel file: {e}")
            return

        df_data = self._filter_vehicle_rows(df_data)
        df_coo = self._filter_vehicle_rows(df_coo)

        self.stdout.write("Processing COO Breakdown...")
        # Group by vehicle signature
        coo_grouped = df_coo.groupby(['Make', 'Model', 'Variant', 'Year'])
        
        vehicles_to_create = []
        count = 0
        
        for (make, model, variant, year), group in coo_grouped:
            try:
                base_row = group.iloc[0]
                
                vehicle_mask = (
                    (df_data['Make'] == make) &
                    (df_data['Model'] == model) &
                    (df_data['Variant'] == variant) &
                    (df_data['Year'] == year)
                )
                data_group = df_data[vehicle_mask]
                
                # Setup all state-level dictionaries
                driveaway_by_state = {}
                ctp_by_state = {}
                comprehensive_by_state = {}
                rego_by_state = {}
                coo_5yr_by_state = {}
                
                fuel_cost_by_state = {}
                electricity_cost_by_state = {}
                ev_levy_by_state = {}
                base_coo_by_state = {}
                components_sum_by_state = {}
                
                mode_data_by_state = {}
                
                # Extract state-level costs from COO_Component_Breakdown
                for _, row in group.iterrows():
                    state = self._safe_str(row['State']).upper()
                    if state:
                        ctp_by_state[state] = self._dollars_to_cents(row.get('ctp_pa'))
                        comprehensive_by_state[state] = self._dollars_to_cents(row.get('comprehensive_pa'))
                        rego_by_state[state] = self._dollars_to_cents(row.get('registration_pa'))
                        fuel_cost_by_state[state] = self._dollars_to_cents(row.get('fuel_cost_pa'))
                        electricity_cost_by_state[state] = self._dollars_to_cents(row.get('electricity_cost_pa'))
                        ev_levy_by_state[state] = self._dollars_to_cents(row.get('ev_levy_pa'))
                        base_coo_by_state[state] = self._dollars_to_cents(row.get('base_coo_pa_canonical'))
                        components_sum_by_state[state] = self._dollars_to_cents(row.get('components_sum_pa'))
                        
                        mode_data_by_state[state] = {}
                
                # Extract mode-specific and state-specific data from v6.3.4 Data
                for _, row in data_group.iterrows():
                    state = self._safe_str(row.get('State')).upper()
                    mode = self._safe_str(row.get('CORE Mode')).upper()
                    
                    if state:
                        if state not in driveaway_by_state:
                            driveaway_by_state[state] = self._dollars_to_cents(row.get('Driveaway Price ($)'))

                        # Total 5yr COO is flattened by taking 'CASH' or the first mode seen
                        if mode == 'CASH' or state not in coo_5yr_by_state:
                            coo_5yr_by_state[state] = self._dollars_to_cents(row.get('Mode 5yr COO ($)'))
                            
                        # Build nested mode data dictionary
                        if state not in mode_data_by_state:
                            mode_data_by_state[state] = {}
                            
                        if mode:
                            mode_data_by_state[state][mode] = {
                                'finance_cost_pa': self._safe_float(row.get('Finance Cost p.a. ($)')),
                                'resale_credit_pa': self._safe_float(row.get('Resale Credit p.a. ($)')),
                                'mode_coo_pa': self._safe_float(row.get('Mode COO p.a. ($)')),
                                'mode_5yr_coo': self._safe_float(row.get('Mode 5yr COO ($)')),
                                'annual_co2_kg': self._safe_float(row.get('Annual CO2 (kg)')),
                                'price_score': self._safe_float(row.get('price_score')),
                                'emissions_score': self._safe_float(row.get('emissions_score')),
                                'core_score': self._safe_float(row.get('core_score')),
                                'stars': self._safe_float(row.get('stars')),
                                'mode_label': self._safe_str(row.get('Mode Label')),
                            }
                
                maintenance_pa = self._dollars_to_cents(base_row.get('maintenance_pa', 0))
                tyre_cost_pa = self._dollars_to_cents(base_row.get('tyre_cost_pa', 0))
                
                data_row = data_group.iloc[0] if not data_group.empty else None
                
                fuel_eff, co2, range_km, battery = None, None, None, None
                fuel_type, body_type = None, ''
                engine_l, drive = None, ''
                is_scoring_outlier = False
                scoring_version = ''
                image_url = ''
                
                if data_row is not None:
                    fuel_eff = self._safe_float(data_row.get('Fuel Eff (L/100km)'))
                    co2 = self._safe_float(data_row.get('CO2 Tailpipe (g/km)'))
                    range_km = self._safe_float(data_row.get('Range (km)'))
                    battery = self._safe_float(data_row.get('Battery (kWh)'))
                    fuel_type = data_row.get('Fuel Type')
                    body_type = self._safe_str(data_row.get('Body Type'))
                    engine_l = self._safe_float(data_row.get('Engine (L)'))
                    drive = self._safe_str(data_row.get('Drive'))
                    is_scoring_outlier = self._safe_bool(data_row.get('is_scoring_outlier'))
                    scoring_version = self._safe_str(data_row.get('scoring_version'))
                    image_url = self._safe_str(data_row.get('Image url '))
                
                v = Vehicle(
                    brand=self._safe_str(make),
                    model=self._safe_str(model),
                    year=self._safe_int(year) or 2026,
                    variant=self._safe_str(variant),
                    body_style=body_type,
                    image_url=image_url if image_url else None,
                    num_seats=5,
                    powertrain_type=self.map_powertrain(fuel_type),
                    
                    fcai_category=self._safe_str(base_row.get('fcai_category')),
                    fcai_broad=self._safe_str(base_row.get('fcai_broad')),
                    energy_norm=self._safe_str(base_row.get('energy_norm')),
                    drive=drive,
                    engine_l=engine_l,
                    battery_kwh=battery,
                    is_scoring_outlier=is_scoring_outlier,
                    scoring_version=scoring_version,
                    
                    driveaway_price_by_state=driveaway_by_state,
                    fuel_consumption_per_100km=fuel_eff,
                    electricity_consumption_per_100km=battery / (range_km / 100) if battery and range_km else None,
                    tailpipe_co2_g_per_km=co2,
                    wltp_range_km=range_km,
                    test_cycle=TestCycle.ADR,
                    
                    annual_km_default=self._safe_int(base_row.get('km_pa_used')) or 13300,
                    insurance_estimate_by_state=comprehensive_by_state,
                    ctp_by_state=ctp_by_state,
                    registration_by_state=rego_by_state,
                    servicing_5yr_estimate=int(maintenance_pa * 5) if maintenance_pa else None,
                    tyre_replacement_estimate=int(tyre_cost_pa * 5) if tyre_cost_pa else None,
                    total_5yr_cost_of_ownership_by_state=coo_5yr_by_state,
                    
                    fuel_cost_by_state=fuel_cost_by_state,
                    electricity_cost_by_state=electricity_cost_by_state,
                    ev_levy_by_state=ev_levy_by_state,
                    base_coo_by_state=base_coo_by_state,
                    components_sum_by_state=components_sum_by_state,
                    mode_data_by_state=mode_data_by_state,
                )
                vehicles_to_create.append(v)
                count += 1
                
                if count % 100 == 0:
                    self.stdout.write(f"Processed {count} vehicles...")
                    
            except Exception as e:
                self.stderr.write(f"Error processing {make} {model} {year}: {e}")
                continue
                
        self.stdout.write(f"Bulk creating {len(vehicles_to_create)} vehicles...")
        Vehicle.objects.bulk_create(vehicles_to_create, batch_size=500)
        self.stdout.write(self.style.SUCCESS(f"Successfully imported {len(vehicles_to_create)} vehicles!"))
