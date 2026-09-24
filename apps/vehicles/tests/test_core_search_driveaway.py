from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.vehicles.models import Vehicle

User = get_user_model()


class CoreSearchDriveawayTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='subscriber@carreb.com.au',
            password='password123',
            subscription_tier='paid'
        )
        self.client.force_authenticate(user=self.user)

        self.v1 = Vehicle.objects.create(
            brand='Alpina',
            model='B3',
            year=2025,
            variant='B3 Sedan',
            fcai_category='Large',
            powertrain_type='petrol',
            tailpipe_co2_g_per_km=220.0,
            driveaway_price_by_state={'NSW': 12900000, 'QLD': 12800000},
            mode_data_by_state={
                'NSW': {
                    'B': {
                        'stars': 3.0,
                        'mode_coo_pa': 20294.47,
                        'mode_5yr_coo': 101472.35,
                        'annual_co2_kg': 3188,
                    }
                }
            }
        )

        self.v2 = Vehicle.objects.create(
            brand='Aston Martin',
            model='Vantage',
            year=2025,
            variant='Coupe',
            fcai_category='Other',
            powertrain_type='petrol',
            tailpipe_co2_g_per_km=245.0,
            driveaway_price_by_state={'NSW': 32500000, 'QLD': 32300000},
            mode_data_by_state={
                'NSW': {
                    'B': {
                        'stars': 3.0,
                        'mode_coo_pa': 43210.00,
                        'mode_5yr_coo': 216050.00,
                        'annual_co2_kg': 3638,
                    }
                }
            }
        )

    def test_search_does_not_override_candidate_driveaway_price(self):
        # User passes their own vehicle's driveaway override ($42,500 = 4250000 cents)
        payload = {
            "target_band_slug": "steady-cruiser",
            "state": "NSW",
            "priority_slider": 3,
            "core_mode": "pure_cost",
            "user_inputs": {
                "annual_km": 15000,
                "driveaway_override": 4250000  # $42,500 from current vehicle
            }
        }
        response = self.client.post('/api/core-rating/search/', data=payload, format='json')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertTrue(len(data) >= 2)

        v_map = {item['brand']: item for item in data}
        
        # Alpina B3 should have $129,000 (12900000 cents), NOT $42,500 (4250000 cents)
        alpina = v_map.get('Alpina')
        self.assertIsNotNone(alpina)
        self.assertEqual(alpina['annual_cost_breakdown']['driveaway_price'], 12900000)
        self.assertEqual(alpina['driveaway_price'], 12900000)
        self.assertEqual(alpina['driveaway_price_display'], '$129,000')

        # Aston Martin should have $325,000 (32500000 cents), NOT $42,500 (4250000 cents)
        aston = v_map.get('Aston Martin')
        self.assertIsNotNone(aston)
        self.assertEqual(aston['annual_cost_breakdown']['driveaway_price'], 32500000)
        self.assertEqual(aston['driveaway_price'], 32500000)
        self.assertEqual(aston['driveaway_price_display'], '$325,000')

    def test_batch_does_not_override_candidate_driveaway_price(self):
        payload = {
            "vehicle_ids": [str(self.v1.id), str(self.v2.id)],
            "state": "NSW",
            "priority_slider": 3,
            "core_mode": "pure_cost",
            "user_inputs": {
                "driveaway_override": 4250000
            }
        }
        response = self.client.post('/api/core-rating/batch/', data=payload, format='json')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 2)
        
        res_v1 = next(item for item in data if item['vehicle_id'] == str(self.v1.id))
        self.assertEqual(res_v1['annual_cost_breakdown']['driveaway_price'], 12900000)
        self.assertEqual(res_v1['driveaway_price'], 12900000)
        
        res_v2 = next(item for item in data if item['vehicle_id'] == str(self.v2.id))
        self.assertEqual(res_v2['annual_cost_breakdown']['driveaway_price'], 32500000)
        self.assertEqual(res_v2['driveaway_price'], 32500000)
