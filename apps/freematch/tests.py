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


class RelaxedSelectorKeepsBudgetCeilingTests(TestCase):
    """B-14: relaxation must be downward-only. Dropping the budget floor is
    fine (cheaper-than-asked is a good suggestion) but cars ABOVE
    budget_max must never appear in suggested matches."""

    def test_relaxed_keeps_budget_ceiling(self):
        from apps.freematch.selectors import get_freematch_candidates_relaxed
        Vehicle.objects.create(
            brand="CheapMake", model="A", year=2026, powertrain_type="petrol",
            driveaway_price_by_state={"NSW": 20_000_00})
        Vehicle.objects.create(
            brand="MidMake", model="B", year=2026, powertrain_type="petrol",
            driveaway_price_by_state={"NSW": 45_000_00})
        Vehicle.objects.create(
            brand="PriceyMake", model="C", year=2026, powertrain_type="petrol",
            driveaway_price_by_state={"NSW": 90_000_00})
        session = FreeMatchSession.objects.create(
            state="NSW", budget_min=40_000, budget_max=50_000)
        brands = set(
            get_freematch_candidates_relaxed(session)
            .values_list("brand", flat=True))
        # Floor relaxed: the $20k car is allowed. Ceiling kept: the $90k
        # car is not.
        self.assertEqual(brands, {"CheapMake", "MidMake"})

    def test_relaxed_without_budget_returns_all(self):
        from apps.freematch.selectors import get_freematch_candidates_relaxed
        Vehicle.objects.create(
            brand="AnyMake", model="A", year=2026, powertrain_type="petrol",
            driveaway_price_by_state={"NSW": 90_000_00})
        session = FreeMatchSession.objects.create(state="NSW")
        self.assertEqual(get_freematch_candidates_relaxed(session).count(), 1)


class BudgetProximityOrderingTests(TestCase):
    """B-14: with equal CORE ratings, matches sort by proximity to the
    asked budget window — not cheapest-first."""

    def _vehicle(self, brand, price_cents):
        return Vehicle.objects.create(
            brand=brand, model="M", year=2026, powertrain_type="petrol",
            driveaway_price_by_state={"NSW": price_cents})

    def test_equal_ratings_sort_by_budget_proximity(self):
        from apps.freematch.services import _score_and_rank
        from unittest import mock

        cheap = self._vehicle("CheapMake", 20_000_00)   # $30k under the floor
        on_target = self._vehicle("TargetMake", 48_000_00)  # inside 45-50k
        with mock.patch("apps.freematch.services.calculate_core_rating") as calc:
            calc.return_value = {
                "core_rating": 4.0, "band_name": "b", "band_slug": "s",
                "total_annual_cost": 10_000_00, "est_cost_difference": None,
            }
            entries = _score_and_rank(
                [cheap, on_target], "NSW", 3,
                budget_min=45_000, budget_max=50_000)
        self.assertEqual([e["vehicle"].brand for e in entries],
                         ["TargetMake", "CheapMake"])

    def test_relaxation_metadata_returned(self):
        from unittest import mock
        from apps.freematch.services import match_vehicle_for_wizard
        self._vehicle("AnyMake", 550_000_00)  # inside 500-600k window
        session = FreeMatchSession.objects.create(
            state="NSW", budget_min=500_000, budget_max=600_000,
            ancap_5_star_only=True)
        with mock.patch("apps.freematch.services.get_freematch_candidates") as strict, \
             mock.patch("apps.freematch.selectors.get_freematch_candidates_relaxed") as relaxed, \
             mock.patch("apps.freematch.services.calculate_core_rating") as calc:
            strict.return_value = Vehicle.objects.none()
            relaxed.return_value = list(Vehicle.objects.all())
            calc.return_value = {
                "core_rating": 4.0, "band_name": "b", "band_slug": "s",
                "total_annual_cost": 10_000_00, "est_cost_difference": None,
            }
            entries, is_suggested, relaxed_filters = \
                match_vehicle_for_wizard(session)
        self.assertTrue(is_suggested)
        self.assertIn("budget_min", relaxed_filters)
        self.assertIn("ancap_5_star_only", relaxed_filters)
