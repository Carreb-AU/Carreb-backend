from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.vehicles.models import (
    Vehicle,
    VehicleIdentity,
    ManualVehicleEnrichment,
    PowertrainType,
    TestCycle,
    InsuranceCategoryBenchmark,
    InsuranceStateModifier,
    RegistrationFeeByState,
    MaintenanceCategoryDefault,
    TyreCategoryDefault,
    FinanceDefault,
    NGAEmissionFactor,
    DepreciationLookup,
)


class VehicleCalculatorLookupAPITestCase(TestCase):
    """
    Test suite for VehicleCalculatorLookupAPIView (`GET /api/v1/vehicles/lookup/`).
    Validates lookup, fallback logic, financial discipline (cents to dollars),
    and exact response structure.
    """

    def setUp(self):
        self.client = APIClient()

        # Seed benchmark defaults
        self.ins_benchmark = InsuranceCategoryBenchmark.objects.create(
            fcai_category='People Mover',
            national_avg_cents_pa=132000,
            estimated_monthly_cents=11000,
        )
        self.ins_modifier = InsuranceStateModifier.objects.create(
            state='NSW',
            avg_comprehensive_cents=155496,
            national_avg_cents=132000,
            state_modifier=1.178,
        )
        self.rego_fee = RegistrationFeeByState.objects.create(
            fcai_category='People Mover',
            state='NSW',
            annual_fee_cents=81000,
        )
        self.maint_default = MaintenanceCategoryDefault.objects.create(
            fcai_category='People Mover',
            representative_vehicle='LDV V80',
            service_interval='12mo / 15,000km',
            five_year_total_cents=175000,
            annual_avg_cents=35000,
            year1_cents=30000,
            year5_cents=40000,
        )
        self.tyre_default = TyreCategoryDefault.objects.create(
            fcai_category='People Mover',
            typical_tyre_size='215/70R16',
            cost_per_set_4_cents=86400,
            replacement_interval_km=60000,
            annualised_cost_cents=21600,
        )
        self.finance_default = FinanceDefault.objects.create(
            fcai_category_broad='Light Commercial',
            deposit_pct=10.0,
            base_rate_pct=7.5,
            alt_fuel_modifier_pct=-1.5,
            term_months=60,
        )
        self.nga_factor = NGAEmissionFactor.objects.create(
            grid='NSW/ACT',
            states_covered='NSW, ACT',
            scope2_factor_kgco2e_per_kwh=0.64,
        )
        self.deprec_l1 = DepreciationLookup.objects.create(
            layer='Layer 1: Category Base Retention (5yr)',
            layer_num=1,
            key='People Mover',
            modifier=0.45,
        )
        self.deprec_l2 = DepreciationLookup.objects.create(
            layer='Layer 2: Energy Type Modifier',
            layer_num=2,
            key='diesel',
            modifier=1.0,
        )
        self.deprec_l3 = DepreciationLookup.objects.create(
            layer='Layer 3: Brand Modifier',
            layer_num=3,
            key='ldv',
            modifier=1.0,
        )

        # Create test vehicle
        self.vehicle = Vehicle.objects.create(
            brand='LDV',
            model='V80',
            year=2025,
            variant='High Roof',
            body_style='People Mover',
            num_seats=5,
            drive='Front',
            powertrain_type=PowertrainType.DIESEL,
            energy_norm='diesel',
            fcai_category='People Mover',
            fcai_broad='Light Commercial',
            engine_l=2.5,
            fuel_consumption_per_100km=8.9,
            wltp_range_km=790.0,
            test_cycle=TestCycle.ADR,
            driveaway_price_by_state={'NSW': 5200000, 'VIC': 5180000},
            tailpipe_co2_g_per_km=230.0,
            mode_data_by_state={
                'NSW': {
                    'B': {'annual_co2_kg': 3153.15, 'mode_coo_pa': 11062.0},
                    'C': {'resale_credit_pa': 5857.98},
                }
            }
        )

    def _make_vehicle(self, brand, model, year, variant, **overrides):
        defaults = dict(
            body_style='SUV',
            num_seats=5,
            drive='Front',
            powertrain_type=PowertrainType.PETROL,
            energy_norm='petrol',
            fcai_category='Medium SUV',
            fcai_broad='SUVs',
            engine_l=2.0,
            fuel_consumption_per_100km=8.0,
            test_cycle=TestCycle.ADR,
            driveaway_price_by_state={'NSW': 4000000},
        )
        defaults.update(overrides)
        return Vehicle.objects.create(brand=brand, model=model, year=year, variant=variant, **defaults)

    def test_lookup_distinguishes_cx5_from_cx3(self):
        """Regression: '2025 Mazda CX-5 Maxx' used to return the CX-3 Maxx Sport."""
        self._make_vehicle('Mazda', 'CX-3', 2025, 'Maxx Sport')
        self._make_vehicle('Mazda', 'CX-5', 2025, 'Maxx')

        url = '/api/v1/vehicles/lookup/?name=2025%20Mazda%20CX-5%20Maxx&state=NSW'
        response = self.client.get(url, HTTP_HOST='localhost')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        vf = response.json()['vehicle_found']
        self.assertEqual(vf['brand'], 'Mazda')
        self.assertEqual(vf['model'], 'CX-5')
        self.assertEqual(vf['variant'], 'Maxx')

    def test_lookup_identity_for_discontinued_year(self):
        """Regression: '2015 Mazda 3 Neo' used to fall back to any 2015 Mazda token match
        (a CX-3) instead of the exact-year VehicleIdentity record."""
        self._make_vehicle('Mazda', 'CX-3', 2025, 'Maxx')
        VehicleIdentity.objects.create(
            make='Mazda',
            model='3',
            year=2015,
            variant='Neo',
            body_style='sedan',
            fcai_category='Small',
            powertrain_type=PowertrainType.PETROL,
            fuel_type_raw='petrol',
            driveaway_price_estimate=2000000,
        )

        url = '/api/v1/vehicles/lookup/?name=2015%20Mazda%203%20Neo&state=NSW'
        response = self.client.get(url, HTTP_HOST='localhost')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        vf = response.json()['vehicle_found']
        self.assertEqual(vf['brand'], 'Mazda')
        self.assertEqual(vf['model'], '3')
        self.assertEqual(vf['year'], 2015)
        self.assertEqual(vf['variant'], 'Neo')

    def test_lookup_without_year_still_matches_catalogue(self):
        """Guard against the AND-token filter being too strict: 'LDV V80' with no year
        must still resolve to the seeded 2025 catalogue vehicle."""
        url = '/api/v1/vehicles/lookup/?name=LDV%20V80&state=NSW'
        response = self.client.get(url, HTTP_HOST='localhost')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['vehicle_found']['model'], 'V80')

    def test_lookup_successful_vehicle_exact_name(self):
        url = '/api/v1/vehicles/lookup/?name=2025%20LDV%20V80%20High%20Roof&state=NSW'
        response = self.client.get(url, HTTP_HOST='localhost')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertTrue(data['success'])
        self.assertEqual(data['query'], '2025 LDV V80 High Roof')

        # Vehicle Found
        vf = data['vehicle_found']
        self.assertEqual(vf['brand'], 'LDV')
        self.assertEqual(vf['model'], 'V80')
        self.assertEqual(vf['variant'], 'High Roof')
        self.assertEqual(vf['year'], 2025)
        self.assertEqual(vf['full_name'], '2025 LDV V80 High Roof')

        # Technical Details (Dollars & Floats)
        tech = data['technical_details']
        self.assertEqual(tech['driveaway_price'], 52000.0)
        self.assertEqual(tech['doors'], 4)
        self.assertEqual(tech['seats'], 5)
        self.assertEqual(tech['drive_type'], 'Front')
        self.assertEqual(tech['energy_type'], 'diesel')
        self.assertEqual(tech['fuel_type'], 'diesel')
        self.assertEqual(tech['fuel_efficiency'], 8.9)
        self.assertIsNone(tech['battery_capacity_kwh'])
        self.assertEqual(tech['range_km'], 790.0)
        self.assertEqual(tech['ancap_rating'], 5)

        # Vehicle Costs p.a.
        costs = data['vehicle_costs_pa']
        self.assertEqual(costs['maintenance_cost'], 350.0)
        self.assertAlmostEqual(costs['insurance_cost'], 1555.0, delta=1.0)
        self.assertEqual(costs['registration_cost'], 810.0)
        self.assertEqual(costs['tyre_cost'], 216.0)
        self.assertGreater(costs['resale_value_est'], 0.0)
        self.assertGreater(costs['depreciation_percentage'], 0.0)

        # Finance
        fin = data['finance']
        self.assertEqual(fin['loan_amount'], 46800.0)  # 10% deposit off $52,000
        self.assertEqual(fin['loan_term_months'], 60)
        self.assertGreater(fin['monthly_repayment'], 0.0)

        # Environment
        env = data['environment']
        self.assertEqual(env['co2_emissions_kg_pa'], 3153)
        self.assertEqual(env['off_grid_energy_pct'], 0)

    def test_lookup_fuzzy_matching_without_year(self):
        url = '/api/v1/vehicles/lookup/?name=LDV%20V80%20High%20Roof'
        response = self.client.get(url, HTTP_HOST='localhost')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['vehicle_found']['model'], 'V80')
        self.assertEqual(data['vehicle_found']['variant'], 'High Roof')

    def test_lookup_missing_name_returns_400(self):
        url = '/api/v1/vehicles/lookup/?state=NSW'
        response = self.client.get(url, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.json()['success'])

    def test_lookup_nonexistent_vehicle_returns_404(self):
        url = '/api/v1/vehicles/lookup/?name=Spaceship%209000&state=NSW'
        response = self.client.get(url, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.json()['success'])

    def test_lookup_via_vehicle_identity_with_enrichment(self):
        # Create VehicleIdentity
        vi = VehicleIdentity.objects.create(
            make='Subaru',
            model='Outback',
            year=2021,
            variant='AWD 2.5i',
            body_style='wagon',
            fcai_category='People Mover',
            powertrain_type=PowertrainType.PETROL,
            fuel_type_raw='petrol',
            fuel_consumption_combined_l_100km=7.3,
            tailpipe_co2_g_per_km=168.0,
            driveaway_price_estimate=4200000,
        )
        ManualVehicleEnrichment.objects.create(
            record=vi,
            ancap_safety_rating=5,
            driveaway_price_estimate=4300000,
            resale_value_5yr_estimate=2200000,
        )

        url = '/api/v1/vehicles/lookup/?name=2021%20Subaru%20Outback%20AWD%202.5i&state=NSW'
        response = self.client.get(url, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['vehicle_found']['brand'], 'Subaru')
        self.assertEqual(data['technical_details']['driveaway_price'], 43000.0)
        self.assertEqual(data['vehicle_costs_pa']['resale_value_est'], 22000.0)
