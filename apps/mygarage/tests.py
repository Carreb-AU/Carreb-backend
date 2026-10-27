from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase as TestCase
from django.urls import reverse

from apps.vehicles.models import Vehicle

User = get_user_model()


def make_vehicle(rating=3.0, **kwargs):
    """Create a vehicle. `rating` is honoured via the rating-engine mock."""
    defaults = dict(
        brand="TestMake",
        model="TestModel",
        year=2026,
        variant="Base",
        body_style="suv",
        fcai_category="Medium SUV",
        powertrain_type="petrol",
        num_seats=5,
        driveaway_price_by_state={"NSW": 50_000_00},
        mode_data_by_state={"NSW": {"B": {"mode_5yr_coo": 200_000_00}}},
    )
    defaults.update(kwargs)
    v = Vehicle.objects.create(**defaults)
    v._test_rating = rating
    return v


def rating_side_effect(vehicle=None, **kwargs):
    driveaway = 0
    if vehicle is not None:
        driveaway = (vehicle.driveaway_price_by_state or {}).get("NSW") or 0
    return {
        "core_rating": getattr(vehicle, "_test_rating", 3.0),
        "band_name": "Good",
        "total_annual_cost": driveaway,
        "est_cost_difference": None,
    }


@mock.patch("apps.mygarage.views.emit_analytics_event")
@mock.patch("apps.mygarage.views.calculate_core_rating", side_effect=rating_side_effect)
@mock.patch("apps.mygarage.views.extract_search_parameters",
            return_value=(True, {"make": "Mazda", "model": "CX-5"}))
class AISmartMatchViewTests(TestCase):
    """Regression tests for the Smart Car Match endpoint.

    Covers the four diagnosed bugs: named cars ignored, alphabetical tie-break,
    variant collapse, and no minimum-results relaxation.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            email="paid@example.com", password="x",
            subscription_tier="core_advantage")
        self.client.force_authenticate(self.user)
        self.url = reverse("ai-smart-match")

    def _post(self, payload=None):
        body = {"query": "Mazda CX-5", "state": "NSW"}
        body.update(payload or {})
        return self.client.post(self.url, body, format="json")

    def test_named_car_is_boosted_above_higher_rated_cars(self, *_mocks):
        make_vehicle(brand="Mazda", model="CX-5", variant="Maxx", rating=3.0)
        make_vehicle(brand="Audi", model="Q5", variant="45", rating=5.0)
        res = self._post()
        self.assertEqual(res.status_code, 200)
        results = res.json()["results"]
        self.assertGreaterEqual(len(results), 2)
        self.assertEqual(results[0]["make"], "Mazda")
        self.assertEqual(results[0]["model"], "CX-5")
        self.assertIn("Your searched car", results[0]["recommendation_reason"])

    def test_multiple_variants_of_named_model_are_returned(self, *_mocks):
        make_vehicle(brand="Mazda", model="CX-5", variant="Maxx Sport", rating=4.0)
        make_vehicle(brand="Mazda", model="CX-5", variant="GT", rating=4.5)
        make_vehicle(brand="Mazda", model="CX-5", variant="Akera", rating=5.0)
        res = self._post()
        variants = [r["variant"] for r in res.json()["results"]
                    if r["model"] == "CX-5"]
        self.assertGreaterEqual(len(variants), 2)

    def test_variant_cap_is_three_per_model(self, *_mocks):
        for i in range(6):
            make_vehicle(brand="Mazda", model="CX-5",
                         variant=f"Variant {i}", rating=4.0 + i * 0.1)
        res = self._post()
        cx5 = [r for r in res.json()["results"] if r["model"] == "CX-5"]
        self.assertLessEqual(len(cx5), 3)

    def test_rating_ties_break_by_cost_not_alphabetical(self, *_mocks):
        make_vehicle(brand="Toyota", model="ZZZ Late Alpha",
                     driveaway_price_by_state={"NSW": 30_000_00}, rating=4.0)
        make_vehicle(brand="Audi", model="AAA Early Alpha",
                     driveaway_price_by_state={"NSW": 60_000_00}, rating=4.0)
        res = self._post()  # AI mock returns Mazda CX-5 filters; neither matches
        results = res.json()["results"]
        self.assertGreaterEqual(len(results), 2)
        # Same rating: the cheaper car must come first despite alphabet order.
        makes = [(r["make"], r["driveaway_price"]) for r in results[:2]]
        self.assertLessEqual(makes[0][1], makes[1][1])

    def test_interpreted_filters_returned(self, *_mocks):
        make_vehicle()
        res = self._post()
        body = res.json()
        self.assertEqual(body["interpreted_filters"]["make"], "Mazda")
        self.assertIn("relaxed_filters", body)


@mock.patch("apps.mygarage.views.emit_analytics_event")
@mock.patch("apps.mygarage.views.calculate_core_rating", side_effect=rating_side_effect)
@mock.patch("apps.mygarage.views.extract_search_parameters",
            return_value=(True, {"num_seats_min": 7, "ancap_rating_min": 5}))
class AISmartMatchRelaxationTests(TestCase):
    """Over-strict filter combinations must relax until >= 5 results."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="paid2@example.com", password="x",
            subscription_tier="core_advantage")
        self.client.force_authenticate(self.user)
        self.url = reverse("ai-smart-match")

    def test_strict_filters_relax_to_minimum_five(self, *_mocks):
        # Only 2 cars satisfy BOTH 7 seats and 5-star ANCAP...
        make_vehicle(brand="Seven", model="Seater A", num_seats=7,
                     variant="v1", rating=4.0)
        make_vehicle(brand="Seven", model="Seater B", num_seats=7,
                     variant="v1", rating=4.0)
        # ...but 5+ more satisfy just 7 seats.
        for i in range(5):
            make_vehicle(brand="Other", model=f"SUV {i}", num_seats=7,
                         variant="v1", rating=3.0)

        res = self.client.post(self.url,
                               {"query": "7 seat SUV 5 star ANCAP", "state": "NSW"},
                               format="json")
        body = res.json()
        self.assertGreaterEqual(len(body["results"]), 5)
        self.assertIn("ancap_rating_min", body["relaxed_filters"])
