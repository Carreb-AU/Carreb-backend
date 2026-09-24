from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.vehicles.models import VehicleCOOComponentBreakdown
from apps.vehicles.cost_estimator_api import (
    calculate_cost_estimate,
    parse_annual_km,
    normalize_fuel_type,
)


class VehicleCostEstimatorAPITestCase(TestCase):
    """
    Test suite for VehicleCostEstimatorAPIView (`GET /api/v1/vehicles/estimate-cost/`).
    Validates cost estimations, variable cost scaling, EV/petrol savings benchmarks,
    grocery weeks calculation, and response formats.
    """

    def setUp(self):
        self.client = APIClient()

        # Seed mock breakdown records across NSW for diesel, petrol, electric, and hybrid
        VehicleCOOComponentBreakdown.objects.create(
            make='Toyota',
            model='Hilux',
            variant='SR5 Double Cab',
            year=2024,
            state='NSW',
            fcai_category='Light Commercial',
            fcai_broad='Light Commercial',
            energy_norm='diesel',
            km_pa_used=15000,
            fuel_cost_pa_cents=300000,          # $3,000 @ 15,000km
            electricity_cost_pa_cents=0,
            comprehensive_pa_cents=150000,      # $1,500
            ctp_pa_cents=50000,                 # $500
            registration_pa_cents=70000,        # $700
            maintenance_pa_cents=45000,         # $450 @ 15,000km
            tyre_cost_pa_cents=30000,           # $300 @ 15,000km
            ev_levy_pa_cents=0,
            components_sum_pa_cents=645000,
        )

        VehicleCOOComponentBreakdown.objects.create(
            make='Toyota',
            model='Corolla',
            variant='Ascent Sport',
            year=2024,
            state='NSW',
            fcai_category='Small',
            fcai_broad='Passenger Cars',
            energy_norm='petrol',
            km_pa_used=15000,
            fuel_cost_pa_cents=225000,          # $2,250 @ 15,000km
            electricity_cost_pa_cents=0,
            comprehensive_pa_cents=120000,      # $1,200
            ctp_pa_cents=50000,                 # $500
            registration_pa_cents=60000,        # $600
            maintenance_pa_cents=35000,         # $350 @ 15,000km
            tyre_cost_pa_cents=25000,           # $250 @ 15,000km
            ev_levy_pa_cents=0,
            components_sum_pa_cents=515000,
        )

        VehicleCOOComponentBreakdown.objects.create(
            make='Tesla',
            model='Model 3',
            variant='RWD',
            year=2024,
            state='NSW',
            fcai_category='Medium',
            fcai_broad='Passenger Cars',
            energy_norm='electric',
            km_pa_used=15000,
            fuel_cost_pa_cents=0,
            electricity_cost_pa_cents=75000,    # $750 @ 15,000km
            comprehensive_pa_cents=180000,      # $1,800
            ctp_pa_cents=50000,                 # $500
            registration_pa_cents=65000,        # $650
            maintenance_pa_cents=15000,         # $150 @ 15,000km
            tyre_cost_pa_cents=35000,           # $350 @ 15,000km
            ev_levy_pa_cents=0,
            components_sum_pa_cents=420000,
        )

        VehicleCOOComponentBreakdown.objects.create(
            make='Toyota',
            model='RAV4',
            variant='GXL Hybrid',
            year=2024,
            state='NSW',
            fcai_category='Medium SUV',
            fcai_broad='SUVs',
            energy_norm='petrol',
            km_pa_used=15000,
            fuel_cost_pa_cents=135000,          # $1,350 @ 15,000km
            electricity_cost_pa_cents=0,
            comprehensive_pa_cents=130000,      # $1,300
            ctp_pa_cents=50000,                 # $500
            registration_pa_cents=65000,        # $650
            maintenance_pa_cents=30000,         # $300 @ 15,000km
            tyre_cost_pa_cents=28000,           # $280 @ 15,000km
            ev_levy_pa_cents=0,
            components_sum_pa_cents=438000,
        )

    def test_parse_annual_km_utility(self):
        self.assertEqual(parse_annual_km(10000), 10000)
        self.assertEqual(parse_annual_km("10,000+ km"), 10000)
        self.assertEqual(parse_annual_km("20,000"), 20000)
        self.assertEqual(parse_annual_km(None, default=15000), 15000)
        self.assertEqual(parse_annual_km("abc", default=15000), 15000)
        # Clamping
        self.assertEqual(parse_annual_km(100), 1000)
        self.assertEqual(parse_annual_km(250000), 150000)

    def test_normalize_fuel_type_utility(self):
        self.assertEqual(normalize_fuel_type("Diesel"), "diesel")
        self.assertEqual(normalize_fuel_type("petrol"), "petrol")
        self.assertEqual(normalize_fuel_type("EV"), "electric")
        self.assertEqual(normalize_fuel_type("bev"), "electric")
        self.assertEqual(normalize_fuel_type("hybrid"), "hybrid")
        self.assertEqual(normalize_fuel_type("PHEV"), "hybrid")

    def test_default_estimate_query(self):
        response = self.client.get('/api/v1/vehicles/estimate-cost/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        
        cost_data = data['data']
        self.assertEqual(cost_data['fuel_type'], 'diesel')
        self.assertEqual(cost_data['state'], 'NSW')
        self.assertEqual(cost_data['annual_km'], 15000)
        self.assertGreater(cost_data['estimated_annual_running_cost'], 0)
        self.assertIn('cost_breakdown', cost_data)
        self.assertIn('potential_saving_vs_ev', cost_data)
        self.assertIn('equivalent_grocery_weeks', cost_data)

    def test_diesel_10k_km_custom_query(self):
        url = '/api/v1/vehicles/estimate-cost/?fuel_type=diesel&annual_km=10000&state=NSW'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res = response.json()['data']

        self.assertEqual(res['fuel_type'], 'diesel')
        self.assertEqual(res['annual_km'], 10000)
        # Scaled variable costs (10k / 15k = 2/3):
        # fuel: 3000 * 2/3 = 2000
        # maint: 450 * 2/3 = 300
        # tyres: 300 * 2/3 = 200
        # fixed: ins 2000, rego 700
        # total = 2000 + 300 + 200 + 2000 + 700 = 5200
        self.assertEqual(res['estimated_annual_running_cost'], 5200.0)
        self.assertEqual(res['estimated_annual_running_cost_display'], '$5,200')
        self.assertEqual(res['cost_breakdown']['fuel_or_electricity'], 2000.0)
        self.assertEqual(res['cost_breakdown']['insurance'], 2000.0)
        self.assertEqual(res['cost_breakdown']['registration'], 700.0)
        self.assertEqual(res['cost_breakdown']['maintenance'], 300.0)
        self.assertEqual(res['cost_breakdown']['tyres'], 200.0)

        # EV at 10k:
        # elec: 750 * 2/3 = 500
        # maint: 150 * 2/3 = 100
        # tyres: 350 * 2/3 = 233.33
        # ins: 2300, rego: 650
        # ev total = 500 + 100 + 233.33 + 2300 + 650 = 3783.33
        # saving vs EV = 5200 - 3783.33 = 1416.67
        self.assertAlmostEqual(res['potential_saving_vs_ev'], 1416.67, places=1)
        self.assertGreater(res['equivalent_grocery_weeks'], 0)
        self.assertIn('grocery bills per year', res['grocery_comparison_text'])

    def test_electric_vehicle_query(self):
        url = '/api/v1/vehicles/estimate-cost/?fuel_type=electric&annual_km=15000&state=NSW'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res = response.json()['data']

        self.assertEqual(res['fuel_type'], 'electric')
        self.assertEqual(res['potential_saving_vs_ev'], 0.0)
        # Should report savings against petrol vehicle
        self.assertGreater(res['potential_saving_vs_petrol'], 0)
        self.assertIn('saved per year compared to petrol', res['grocery_comparison_text'])

    def test_string_km_with_plus_formatting(self):
        url = '/api/v1/vehicles/estimate-cost/?fuel_type=petrol&annual_km=10,000+%20km&state=NSW'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res = response.json()['data']
        self.assertEqual(res['annual_km'], 10000)

    def test_state_fallback(self):
        url = '/api/v1/vehicles/estimate-cost/?fuel_type=petrol&state=INVALID_STATE'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res = response.json()['data']
        self.assertEqual(res['state'], 'NSW')

    def test_alias_endpoint(self):
        url = '/api/vehicles/estimate-cost/?fuel_type=diesel'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], 'success')
