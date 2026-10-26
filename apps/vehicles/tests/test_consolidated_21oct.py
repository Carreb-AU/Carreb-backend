"""21-Oct-26 workbook layout tests.

The 21-Oct file inserted new leading columns (listing_id at 0, is_suppressed
at 8, ...), so any positional column mapping misparses it. These tests build
a tiny synthetic workbook in the NEW 116-column layout — two listings (one
suppressed) sharing one name group — and run both the consolidated importer
and the CORE Dial parser over it. The OLD-layout golden parse is covered by
GoldenWorkbookTests in test_core_dial.py.
"""
import os
import tempfile

import openpyxl
from django.test import TestCase

from apps.vehicles.models import ConsolidatedVehicleRow, Vehicle
from apps.vehicles.services.consolidated_import import import_consolidated_vehicles
from apps.vehicles.services.core_dial import AU_STATES, dollars_to_cents
from apps.vehicles.services.core_dial_import import parse_workbook

SHEET_NAME = 'Consolidated Vehicles v6.4'

# Exact header of the real 21-Oct-26 sheet (116 columns).
HEADERS = [
    'listing_id', 'Make', 'Model', 'Variant', 'Year', 'State', 'CORE Mode',
    'Mode Label', 'is_suppressed', 'Fuel Type', 'Energy (norm)',
    'energy_type (v6.4 enum)', 'base_fuel', 'Body Type', 'Drive',
    'transmission', 'Seats', 'Doors', 'Engine (L)', 'Battery (kWh)',
    'fcai_category', 'fcai_broad', 'cost_category (15-cat tables)',
    'AU Launch (Month / Year)', 'gvg_vehicleDisplayId',
    'Fuel Eff (L/100km)', 'phev_fuel_consumption_l100',
    'energy_consumption_wh_km', 'CO2 Tailpipe (g/km)', 'fuel_tank_l',
    'Driveaway Price ($)', 'km_pa_used', 'fuel_cost_pa',
    'electricity_cost_pa', 'ctp_pa', 'comprehensive_pa', 'registration_pa',
    'maintenance_pa', 'tyre_cost_pa', 'ruc_pa', 'Base COO p.a. ($)',
    'maintenance_yr1', 'maintenance_yr2', 'maintenance_yr3',
    'maintenance_yr4', 'maintenance_yr5', 'maintenance_5yr_total',
    'finance_apr_pct', 'total_interest_5yr', 'finance_fees_5yr',
    'finance_cost_5yr', 'Finance Cost p.a. ($)',
    'retention_factor (L1×L2×L3)', 'resale_value_5yr',
    'Resale Credit p.a. ($)', 'Mode COO p.a. ($)', 'Mode 5yr COO ($)',
    'co2_energy_cycle_g_km', 'Annual CO2 (kg)', 'electric_share',
    'offgrid_share', 'fuel_l100_used', 'co2_fuel_g_km', 'co2_grid_g_km',
    'co2_tailpipe_pa_kg', 'Range (km)', 'range_total_km',
    'range_battery_km', 'range_petrol_km', 'drivetrain (range basis)',
    'range_ladder_step (Calc §2.11)', 'range_estimated_badge',
    'price_score', 'emissions_score', 'core_score', 'core_rating_1dp',
    'co2_cap_tier', 'core_rating_capped', 'stars', 'band_name',
    'is_scoring_outlier', 'scoring_version', 'spotlight_range_kings',
    'spotlight_green_lean', 'spotlight_unicorn_match',
    'spotlight_category_sweep', 'spotlight_core_allstars',
    'spotlight_count', 'spotlight_badges', 'spotlight_version',
    'Price Type', 'price_basis', 'fe_basis', 'co2_basis',
    'co2_energy_cycle_basis', 'range_basis', 'range_prior_value',
    'range_research_note', 'seats_basis', 'doors_basis',
    'transmission_basis', 'wh_km_source', 'phev_cs_basis',
    'maintenance_source_tier', 'maintenance_basis', 'assumption_fills',
    'data_flags', 'Research Status', 'Source', 'Notes / Action for Ali',
    'source_tab', 'source_id', 'legal_basis', 'attribution_text',
    'permitted_uses', 'expiry_at',
]

MAKE, MODEL, VARIANT, YEAR = 'TestMake', 'Corolla', 'Ascent Sport', 2026

# Mode B parts (dollars p.a.) — must sum to MODE_B_COO for a clean parse.
PARTS = {
    'fuel_cost_pa': 0.0,
    'electricity_cost_pa': 800.0,
    'ctp_pa': 600.0,
    'comprehensive_pa': 1500.0,
    'registration_pa': 800.0,
    'maintenance_pa': 500.0,
    'tyre_cost_pa': 400.0,
    'ruc_pa': 300.0,
}
MODE_B_COO = sum(PARTS.values())  # 4900.0
DRIVEAWAY = 35000.0


def _row(listing_id, suppressed, state, mode):
    row = {h: None for h in HEADERS}
    row.update({
        'listing_id': listing_id,
        'Make': MAKE, 'Model': MODEL, 'Variant': VARIANT, 'Year': YEAR,
        'State': state, 'CORE Mode': mode,
        'Mode Label': {'B': 'Pure Cost', 'E': 'Cool Choice',
                       'C': 'Captain Carbon', 'F': 'Full Picture'}[mode],
        'is_suppressed': suppressed,
        'Fuel Type': 'Electric', 'Energy (norm)': 'electric',
        'energy_type (v6.4 enum)': 'bev', 'base_fuel': 'electric',
        'Body Type': 'Hatch', 'Drive': 'FWD', 'transmission': 'Automatic',
        # Seats differ between listings: first listing has 5, second 7 —
        # the Vehicle must take the FIRST listing's value.
        'Seats': 7 if listing_id == 'L002' else 5,
        'Doors': 4, 'Battery (kWh)': 60.0,
        'fcai_category': 'Small', 'fcai_broad': 'Small',
        'Driveaway Price ($)': DRIVEAWAY, 'km_pa_used': 13300,
        'Base COO p.a. ($)': MODE_B_COO,
        'maintenance_yr1': 100.0, 'maintenance_yr2': 200.0,
        'maintenance_yr3': 300.0, 'maintenance_yr4': 400.0,
        'maintenance_yr5': 500.0, 'maintenance_5yr_total': 1500.0,
        'maintenance_source_tier': 'OEM schedule',
        'maintenance_basis': 'scheduled servicing',
        'Mode COO p.a. ($)': MODE_B_COO, 'Mode 5yr COO ($)': MODE_B_COO * 5,
        'co2_energy_cycle_g_km': 0.0, 'Annual CO2 (kg)': 900.0,
        'electric_share': 1.0, 'offgrid_share': 0.0,
        'fuel_l100_used': 0.0, 'co2_fuel_g_km': 0.0,
        'co2_grid_g_km': 0.0, 'co2_tailpipe_pa_kg': 0.0,
        'Range (km)': 450.0, 'price_score': 0.5, 'emissions_score': 0.6,
        'core_score': 0.55, 'core_rating_1dp': 3.0, 'stars': 4.0,
        'band_name': 'Balanced', 'is_scoring_outlier': False,
        'scoring_version': 'v6.4-test-21oct', 'Price Type': 'Driveaway',
        'price_basis': 'manufacturer RRP', 'fe_basis': 'label',
        'co2_basis': 'label', 'co2_energy_cycle_basis': 'N/A (BEV)',
        'energy_consumption_wh_km': 171.0,
        'Research Status': 'Confirmed', 'Source': 'test',
        'source_tab': 'test-tab',
    })
    if mode == 'B':
        row.update(PARTS)
    return row


def build_workbook(path):
    """2 listings (L001 on sale, L002 suppressed) × 8 states × 4 modes."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append(HEADERS)
    for listing_id, suppressed in (('L001', False), ('L002', True)):
        for state in AU_STATES:
            for mode in ('B', 'E', 'C', 'F'):
                r = _row(listing_id, suppressed, state, mode)
                ws.append([r[h] for h in HEADERS])
    wb.save(path)


class NewLayoutImportTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmpdir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.tmpdir, 'synthetic-21oct.xlsx')
        build_workbook(cls.path)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_import_writes_vehicle_and_source_rows(self):
        result = import_consolidated_vehicles(self.path)
        self.assertEqual(result['vehicles_seen'], 1)  # one name group
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['source_rows_written'], 64)

        self.assertEqual(ConsolidatedVehicleRow.objects.count(), 64)

        vehicle = Vehicle.objects.get(
            brand=MAKE, model=MODEL, variant=VARIANT, year=YEAR,
        )
        # 21-Oct scalar additions — from the group's first listing.
        self.assertEqual(vehicle.transmission, 'Automatic')
        self.assertEqual(vehicle.doors, 4)
        self.assertEqual(vehicle.num_seats, 5)  # first listing, not 7
        self.assertEqual(vehicle.base_fuel, 'electric')
        self.assertEqual(vehicle.energy_consumption_wh_km, 171.0)
        # BEV flat 18.0 kWh/100km convention kept; sheet value stored above.
        self.assertEqual(vehicle.electricity_consumption_per_100km, 18.0)
        self.assertEqual(vehicle.co2_energy_cycle_basis, 'N/A (BEV)')
        self.assertEqual(vehicle.maintenance_5yr_detail, {
            'yr1_cents': 10000, 'yr2_cents': 20000, 'yr3_cents': 30000,
            'yr4_cents': 40000, 'yr5_cents': 50000, 'total_cents': 150000,
            'source_tier': 'OEM schedule', 'basis': 'scheduled servicing',
        })
        # Only one of the two listings is suppressed -> Vehicle is not.
        self.assertFalse(vehicle.is_suppressed)

        # Every source row is stored verbatim and linked to the vehicle.
        row = ConsolidatedVehicleRow.objects.filter(listing_id='L001').first()
        self.assertEqual(row.vehicle_id, vehicle.id)
        self.assertEqual(row.source_row, 2)  # first data row of the sheet
        self.assertEqual(row.data['Make'], MAKE)
        self.assertEqual(row.data['listing_id'], 'L001')
        self.assertEqual(row.data['Mode COO p.a. ($)'], MODE_B_COO)
        suppressed = ConsolidatedVehicleRow.objects.filter(listing_id='L002')
        self.assertEqual(suppressed.count(), 32)
        self.assertTrue(suppressed.first().is_suppressed)

    def test_reimport_replaces_rows_idempotently(self):
        import_consolidated_vehicles(self.path)
        import_consolidated_vehicles(self.path)
        self.assertEqual(ConsolidatedVehicleRow.objects.count(), 64)
        self.assertEqual(Vehicle.objects.count(), 1)

    def test_mode_data_carries_co2_energy_detail(self):
        import_consolidated_vehicles(self.path)
        vehicle = Vehicle.objects.get(
            brand=MAKE, model=MODEL, variant=VARIANT, year=YEAR,
        )
        mode_b = vehicle.mode_data_by_state['NSW']['B']
        self.assertEqual(mode_b['electric_share'], 1.0)
        self.assertEqual(mode_b['offgrid_share'], 0.0)
        self.assertEqual(mode_b['fuel_l100_used'], 0.0)
        self.assertEqual(mode_b['co2_fuel_g_km'], 0.0)
        self.assertEqual(mode_b['co2_grid_g_km'], 0.0)
        self.assertEqual(mode_b['co2_tailpipe_pa_kg'], 0.0)

    def test_dial_parse_skips_suppressed_listing(self):
        import_consolidated_vehicles(self.path)  # rows exist; dial is parse-only
        parsed = parse_workbook(self.path, as_at='2026-10-21')
        self.assertEqual(len(parsed.listings), 2)
        statuses = sorted(l.research_status for l in parsed.listings)
        self.assertEqual(statuses, ['Confirmed', 'Confirmed'])
        self.assertEqual(
            sorted(l.is_suppressed for l in parsed.listings), [False, True],
        )

        rows = parsed.dial_rows()
        # Only the unsuppressed listing produces rows: 8 states.
        self.assertEqual(len(rows), 8)
        self.assertEqual({r.state for r in rows}, set(AU_STATES))
        self.assertEqual(parsed.skipped_suppressed, 1)
        self.assertEqual(parsed.problems, [])

        r = next(r for r in rows if r.state == 'NSW')
        self.assertEqual(r.driveaway_cents, dollars_to_cents(DRIVEAWAY))
        self.assertEqual(r.coo_pa_cents, dollars_to_cents(MODE_B_COO))
        self.assertEqual(r.coo_pa_cents, sum(r.parts_cents.values()))
        self.assertEqual(r.price_basis, 'manufacturer RRP')
