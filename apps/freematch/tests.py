from django.test import TestCase

from apps.freematch.models import FreeMatchSession
from apps.freematch.services import _build_match_vehicle_entry, build_match_response
from apps.vehicles.models import Vehicle


def make_entry(**overrides):
    vehicle = Vehicle(
        brand="TestMake",
        model="TestModel",
        year=2026,
        variant="Base",
        body_style="suv",
        num_seats=5,
        powertrain_type="petrol",
        image_url="/media/test.jpg",
        tailpipe_co2_g_per_km=150.0,
        driveaway_price_by_state={"NSW": 50_000_00},
        resale_value_5yr_estimate=25_000_00,
    )
    entry = {
        "vehicle": vehicle,
        "core_rating": 4.2,
        "band_name": "Smart Move™",
        "band_slug": "smart-move",
        "total_annual_cost": 12_345_00,
        "est_cost_difference": None,
    }
    entry.update(overrides)
    return entry


class MatchVehicleEntryTests(TestCase):
    """Regression: results 2-5 on the Smart Car Finder results screen showed
    no price/spec data because the gated fields were hard-locked for every
    entry. All entries must now carry real values."""

    def test_cost_fields_are_unlocked_and_populated(self):
        v = _build_match_vehicle_entry(make_entry(), "NSW")
        self.assertEqual(v["driveaway_price_estimate"], {"locked": False, "value": 50_000_00})
        self.assertEqual(v["driveaway_price_display"], "$50,000")
        self.assertEqual(v["resale_value_5yr_estimate"], {"locked": False, "value": 25_000_00})
        self.assertEqual(v["resale_value_5yr_display"], "$25,000")
        self.assertEqual(v["est_cost_difference"], {"locked": False, "value": None})
        self.assertIsNone(v["est_cost_difference_display"])

    def test_display_fields_present(self):
        v = _build_match_vehicle_entry(make_entry(), "NSW")
        self.assertEqual(v["image_url"], "/media/test.jpg")
        self.assertEqual(v["body_style"], "suv")
        self.assertEqual(v["num_seats"], 5)
        self.assertEqual(v["band_slug"], "smart-move")

    def test_no_state_price_is_null_not_locked(self):
        vehicle = Vehicle(
            brand="TestMake", model="TestModel", year=2026, variant="Base",
            driveaway_price_by_state={"VIC": 40_000_00},
        )
        entry = make_entry(vehicle=vehicle)
        v = _build_match_vehicle_entry(entry, "NSW")
        self.assertEqual(v["driveaway_price_estimate"], {"locked": False, "value": None})
        self.assertIsNone(v["driveaway_price_display"])


class MatchResponseTests(TestCase):
    def test_all_five_entries_have_real_values(self):
        session = FreeMatchSession(session_token="t" * 32, state="NSW")
        entries = [make_entry() for _ in range(5)]
        resp = build_match_response(entries, session)
        self.assertEqual(resp["result_count"], 5)
        for veh in resp["vehicles"]:
            self.assertFalse(veh["driveaway_price_estimate"]["locked"])
            self.assertEqual(veh["driveaway_price_estimate"]["value"], 50_000_00)
            self.assertFalse(veh["resale_value_5yr_estimate"]["locked"])
            self.assertEqual(veh["image_url"], "/media/test.jpg")
