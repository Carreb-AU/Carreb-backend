from django.test import TestCase

from apps.vehicles.models import VehicleIdentity
from apps.vehicles.services.gvg_import import build_vehicle_like_from_gvg
from apps.vehicles.services.rating_engine import calculate_core_rating


class GVGNoCoreScoreTest(TestCase):
    """
    Regression test for the spec boundary: GVG / legacy / current vehicles
    must NEVER receive a CORE score. Only Carreb catalogue vehicles may be
    scored (Dev Spec §4, Decision Note / Type-Ahead §4).
    """

    def test_gvg_record_returns_no_core_rating(self):
        record = VehicleIdentity.objects.create(
            make='Toyota',
            model='Camry',
            year=2015,
            variant='Altise',
            body_style='sedan',
            fcai_category='Medium',
            fcai_broad='Passenger Cars',
            powertrain_type='petrol',
            fuel_type_raw='petrol',
            fuel_consumption_combined_l_100km=7.8,
            tailpipe_co2_g_per_km=182.0,
            source_dataset='GVG-CURRENT',
            test_cycle='ADR',
        )

        vehicle_like = build_vehicle_like_from_gvg(record, state='NSW')
        result = calculate_core_rating(
            vehicle_like,
            state='NSW',
            priority_slider=3,
            core_mode='pure_cost',
            user_inputs={},
        )

        self.assertIsNone(result['core_rating'])
        self.assertEqual(result['band_name'], '')
        self.assertEqual(result['band_slug'], '')
        self.assertIn(
            'only available for carreb catalogue vehicles',
            result.get('message', '').lower(),
        )
        self.assertTrue(result['is_estimate'])
