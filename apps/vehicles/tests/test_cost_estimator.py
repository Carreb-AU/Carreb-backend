from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.vehicles.models import CoreDialBatch, CoreDialRow, Vehicle
from apps.vehicles.cost_estimator_api import (
    calculate_cost_estimate,
    parse_annual_km,
    normalize_fuel_type,
)


def _dial_row(batch, version_id, vehicle, **costs):
    defaults = dict(
        batch=batch, version_id=version_id,
        model_id=f'm{version_id:06d}', state='NSW',
        make=vehicle.brand, model=vehicle.model,
        variant=vehicle.variant, year=vehicle.year,
        fcai_category=vehicle.fcai_category,
        driveaway_cents=3000000, coo_pa_cents=500000,
        annual_co2_kg=2000.0, co2_g_per_km=140.0,
        price_score=0.5, emissions_score=0.5, co2_cap=None,
        fuel_cents=0, electricity_cents=0,
        ctp_cents=50000, comprehensive_cents=150000,
        registration_cents=60000, servicing_cents=30000,
        tyres_cents=25000, road_user_charge_cents=0,
    )
    defaults.update(costs)
    return CoreDialRow.objects.create(vehicle=vehicle, **defaults)


class VehicleCostEstimatorAPITestCase(TestCase):
    """
    Test suite for VehicleCostEstimatorAPIView (`GET /api/v1/vehicles/estimate-cost/`).
    Validates cost estimations, variable cost scaling, EV/petrol savings
    benchmarks, grocery weeks calculation, and response formats.

    The estimator reads the CURRENT CORE Dial batch (live rows of the
    current load only), so fixtures seed vehicles + dial rows.
    """

    def setUp(self):
        self.client = APIClient()
        batch = CoreDialBatch.objects.create(
            scoring_version='v-test', as_at='2026-11-07', is_current=True)

        def v(brand, model, variant, energy_norm, category, broad):
            return Vehicle.objects.create(
                brand=brand, model=model, variant=variant, year=2024,
                body_style='sedan', fcai_category=category, fcai_broad=broad,
                powertrain_type='petrol', energy_norm=energy_norm,
                annual_km_default=15000)

        # Diesel Hilux — the default query's target
        hilux = v('Toyota', 'Hilux', 'SR5 Double Cab', 'diesel',
                  'Light Commercial', 'Light Commercial')
        _dial_row(batch, 1, hilux,
                  fuel_cents=300000,              # $3,000 @ 15,000km
                  comprehensive_cents=150000,     # $1,500
                  ctp_cents=50000,                # $500
                  registration_cents=70000,       # $700
                  servicing_cents=45000,          # $450 @ 15,000km
                  tyres_cents=30000)              # $300 @ 15,000km

        # Petrol Corolla
        corolla = v('Toyota', 'Corolla', 'Ascent Sport', 'petrol',
                    'Small', 'Passenger Cars')
        _dial_row(batch, 2, corolla,
                  fuel_cents=225000,              # $2,250
                  comprehensive_cents=120000,
                  ctp_cents=50000,
                  registration_cents=60000,
                  servicing_cents=35000,
                  tyres_cents=25000)

        # BEV Model 3
        model3 = v('Tesla', 'Model 3', 'RWD', 'bev', 'Medium', 'Passenger Cars')
        _dial_row(batch, 3, model3,
                  electricity_cents=75000,        # $750
                  comprehensive_cents=180000,
                  ctp_cents=50000,
                  registration_cents=65000,
                  servicing_cents=15000,
                  tyres_cents=35000)

        # Full hybrid RAV4 — the only row the 'hybrid' bucket may count
        rav4 = v('Toyota', 'RAV4', 'GXL Hybrid', 'hev', 'Medium SUV', 'SUVs')
        _dial_row(batch, 4, rav4,
                  fuel_cents=135000,
                  comprehensive_cents=130000,
                  ctp_cents=50000,
                  registration_cents=65000,
                  servicing_cents=30000,
                  tyres_cents=28000)

        # Decoys: mild hybrid and PHEV must NOT count in the hybrid sample
        mhev = v('Toyota', 'Corolla Cross', 'Atmos', 'mhev', 'Small SUV', 'SUVs')
        _dial_row(batch, 5, mhev, fuel_cents=150000)
        phev = v('Mitsubishi', 'Outlander', 'Exceed', 'phev', 'Medium SUV', 'SUVs')
        _dial_row(batch, 6, phev,
                  fuel_cents=100000, electricity_cents=40000)

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
        self.assertEqual(normalize_fuel_type("PHEV"), "phev")
        self.assertEqual(normalize_fuel_type("plug-in hybrid"), "phev")
        self.assertEqual(normalize_fuel_type("mild_hybrid"), "mild_hybrid")
        self.assertEqual(normalize_fuel_type("mhev"), "mild_hybrid")
        with self.assertRaises(ValueError):
            normalize_fuel_type("banana")

    def test_unknown_fuel_type_returns_400(self):
        resp = self.client.get(
            '/api/v1/vehicles/estimate-cost/?fuel_type=banana')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()['status'], 'error')

    def test_default_estimate_query(self):
        response = self.client.get('/api/v1/vehicles/estimate-cost/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['status'], 'success')

        cost_data = data['data']
        self.assertEqual(cost_data['fuel_type'], 'diesel')
        self.assertEqual(cost_data['state'], 'NSW')
        self.assertEqual(cost_data['annual_km'], 15000)
        self.assertEqual(cost_data['sample_size'], 1)
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
        # grocery weeks (baseline 207, half-up): floor(1416.67/207 + 0.5) = 7
        self.assertAlmostEqual(res['potential_saving_vs_ev'], 1416.67, places=1)
        self.assertEqual(res['equivalent_grocery_weeks'], 7)
        self.assertIn('about the same as 7 weeks', res['grocery_comparison_text'])
        self.assertIn('average household grocery shop', res['grocery_comparison_text'])

    def test_electric_vehicle_query(self):
        url = '/api/v1/vehicles/estimate-cost/?fuel_type=electric&annual_km=15000&state=NSW'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res = response.json()['data']

        self.assertEqual(res['fuel_type'], 'electric')
        self.assertEqual(res['sample_size'], 1)      # the bev only
        self.assertEqual(res['potential_saving_vs_ev'], 0.0)
        # Saving basis for EVs is petrol; against itself it is exactly zero,
        # so no grocery line.
        self.assertGreater(res['potential_saving_vs_petrol'], 0)
        self.assertIn('about the same as', res['grocery_comparison_text'])
        self.assertIn('average household grocery shop', res['grocery_comparison_text'])

    def test_mild_hybrid_and_phev_are_separate_buckets(self):
        """mhev and phev are their own fuel types with their own samples,
        never lumped into 'hybrid'."""
        for fuel, expected in (('mild_hybrid', 1), ('phev', 1)):
            resp = self.client.get(
                f'/api/v1/vehicles/estimate-cost/?fuel_type={fuel}&state=NSW')
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            res = resp.json()['data']
            self.assertEqual(res['fuel_type'], fuel)
            self.assertEqual(res['sample_size'], expected)

    def test_more_expensive_type_reports_extra_cost(self):
        """No clamping: when the selected type costs more than the
        comparison, the payload reports an extra cost and no grocery line."""
        from unittest import mock
        from apps.vehicles import cost_estimator_api as ce

        def fake_components(fuel_norm, state, category=None):
            # Diesel deliberately costs LESS than the EV baseline, so the
            # "saving vs EV" goes negative and must surface as an extra cost.
            table = {
                'diesel': dict(sample_count=3, avg_km=15000,
                               avg_fuel=100000, avg_elec=0, avg_maint=100000,
                               avg_tyre=50000, avg_ev_levy=0, avg_ctp=50000,
                               avg_comp=200000, avg_rego=70000),
                'electric': dict(sample_count=3, avg_km=15000,
                                 avg_fuel=0, avg_elec=900000, avg_maint=80000,
                                 avg_tyre=40000, avg_ev_levy=0, avg_ctp=50000,
                                 avg_comp=150000, avg_rego=60000),
                'petrol': dict(sample_count=3, avg_km=15000,
                               avg_fuel=400000, avg_elec=0, avg_maint=80000,
                               avg_tyre=40000, avg_ev_levy=0, avg_ctp=50000,
                               avg_comp=150000, avg_rego=60000),
            }
            return table[fuel_norm]

        with mock.patch.object(ce, '_query_aggregated_components', fake_components):
            res = ce.calculate_cost_estimate(raw_fuel='diesel', raw_km=15000,
                                             raw_state='NSW')
        self.assertLess(res['potential_saving_vs_ev'], 0)
        self.assertEqual(res['grocery_comparison_text'], '')
        self.assertEqual(res['equivalent_grocery_weeks'], 0)
        self.assertIn('Estimated extra cost against EV', res['summary_disclaimer'])

    def test_hybrid_bucket_counts_full_hybrids_only(self):
        """The hybrid sample is energy_norm 'hev' only — mild hybrids (mhev)
        and PHEVs are separate buckets and must not be counted."""
        url = '/api/v1/vehicles/estimate-cost/?fuel_type=hybrid&annual_km=15000&state=NSW'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res = response.json()['data']
        self.assertEqual(res['fuel_type'], 'hybrid')
        self.assertEqual(res['sample_size'], 1)      # RAV4 hev only

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
