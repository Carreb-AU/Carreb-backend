from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase as TestCase
from django.urls import reverse

from apps.vehicles.models import Vehicle
from apps.mygarage.models import GarageVehicle, GarageVehicleSource

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


@mock.patch("apps.mygarage.views.emit_analytics_event")
@mock.patch("apps.mygarage.views.calculate_core_rating", side_effect=rating_side_effect)
@mock.patch("apps.mygarage.views.extract_search_parameters",
            return_value=(True, {"budget_max": 20000, "core_rating_min": 4.5}))
class AISmartMatchBudgetRelaxTests(TestCase):
    """Budget + core-rating combos must relax rather than return nothing."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="paid3@example.com", password="x",
            subscription_tier="core_advantage")
        self.client.force_authenticate(self.user)
        self.url = reverse("ai-smart-match")

    def test_impossible_budget_and_rating_relaxes(self, *_mocks):
        # Only 1 car under $20k; none at 4.5+ rating under $20k.
        make_vehicle(brand="Cheap", model="Runabout", rating=3.0,
                     driveaway_price_by_state={"NSW": 18_000_00})
        for i in range(6):
            make_vehicle(brand="Other", model=f"Car {i}", rating=4.0,
                         driveaway_price_by_state={"NSW": 40_000_00})
        res = self.client.post(self.url,
                               {"query": "great car under 20000", "state": "NSW"},
                               format="json")
        body = res.json()
        self.assertGreaterEqual(len(body["results"]), 5)
        self.assertIn("core_rating_min", body["relaxed_filters"])
        self.assertIn("budget_max", body["relaxed_filters"])


@mock.patch("apps.mygarage.views.emit_analytics_event")
@mock.patch("apps.mygarage.views.calculate_core_rating", side_effect=rating_side_effect)
@mock.patch("apps.mygarage.views.extract_search_parameters",
            return_value=(True, {"budget_max": 40000}))
class AISmartMatchUnknownPriceTests(TestCase):
    """Vehicles with no driveaway price for the state must not leak into
    budget-constrained results."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="paid4@example.com", password="x",
            subscription_tier="core_advantage")
        self.client.force_authenticate(self.user)
        self.url = reverse("ai-smart-match")

    def test_unknown_price_excluded_from_budget_results(self, *_mocks):
        make_vehicle(brand="Seed", model="NoPrice",
                     driveaway_price_by_state={}, rating=5.0)
        for i in range(6):
            make_vehicle(brand="Priced", model=f"Right {i}",
                         driveaway_price_by_state={"NSW": 35_000_00}, rating=4.0)
        res = self.client.post(self.url,
                               {"query": "suv under 40000", "state": "NSW"},
                               format="json")
        results = res.json()["results"]
        self.assertGreaterEqual(len(results), 5)
        self.assertFalse(any(r["make"] == "Seed" for r in results))

    def test_unknown_price_ok_without_budget(self, *_mocks):
        make_vehicle(brand="Seed", model="NoPrice",
                     driveaway_price_by_state={}, rating=5.0)
        res = self.client.post(self.url,
                               {"query": "any car", "state": "NSW"},
                               format="json")
        # No budget in filters for this test's mock... budget_max IS set, so use
        # a second post without budget by overriding the mock return value.
        with mock.patch("apps.mygarage.views.extract_search_parameters",
                        return_value=(True, {})):
            res = self.client.post(self.url,
                                   {"query": "any car", "state": "NSW"},
                                   format="json")
        results = res.json()["results"]
        self.assertTrue(any(r["make"] == "Seed" for r in results))


@mock.patch("apps.mygarage.services._places_search_text")
@mock.patch("apps.mygarage.find_dealer_views.emit_analytics_event")
@override_settings(GOOGLE_PLACES_API_KEY="test-key")
class FindDealerTests(TestCase):
    """Regression tests for the Find-a-Dealer endpoint.

    Covers the diagnosed bugs: geocode failure silently reported as
    "no dealers found", missing phone/website fields, and the missing
    spec-compatible GET route.
    """

    GEOCODE_RESPONSE = ([
        {"location": {"latitude": -33.8688, "longitude": 151.2093}}
    ], None)

    DEALERS_RESPONSE = ([
        {
            "displayName": {"text": "Nearby Motors"},
            "nationalPhoneNumber": "02 9000 0001",
            "websiteUri": "https://nearby.example.com",
            "googleMapsUri": "https://maps.google.com/?cid=1",
            "location": {"latitude": -33.87, "longitude": 151.21},
            "rating": 4.5,
        },
        {
            "displayName": {"text": "Faraway Motors"},
            "nationalPhoneNumber": "02 9000 0002",
            "websiteUri": "",
            "googleMapsUri": "https://maps.google.com/?cid=2",
            "location": {"latitude": -33.9, "longitude": 151.4},
            "rating": 4.0,
        },
    ], None)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = User.objects.create_user(
            email="dealer@example.com", password="x")
        self.client.force_authenticate(self.user)
        self.vehicle = make_vehicle(brand="TestMake")
        self.garage_vehicle = GarageVehicle.objects.create(
            user=self.user, vehicle_catalogue=self.vehicle,
            source=GarageVehicleSource.VEHICLE_LOOKUP,
        )

    def _mock_places(self, m_places, responses):
        m_places.side_effect = list(responses)

    def test_geocode_failure_reports_unavailable_not_empty(self, _m_analytics, m_places):
        # Regression: geocode failure used to return service_unavailable=False,
        # which surfaced to users as "No dealers found".
        m_places.return_value = (None, "billing_or_auth")
        resp = self.client.post(
            reverse("find-dealer"),
            {"garage_vehicle_id": str(self.garage_vehicle.id),
             "postcode": "2000", "radius_km": 25},
            format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["service_unavailable"])
        self.assertNotIn("no_results_message", resp.data)

    def test_results_include_phone_website_and_distance(self, _m_analytics, m_places):
        self._mock_places(m_places, [self.GEOCODE_RESPONSE, self.DEALERS_RESPONSE])
        resp = self.client.post(
            reverse("find-dealer"),
            {"garage_vehicle_id": str(self.garage_vehicle.id),
             "postcode": "2000", "radius_km": 25},
            format="json")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["results"]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["dealer_name"], "Nearby Motors")
        self.assertEqual(results[0]["phone"], "02 9000 0001")
        self.assertEqual(results[0]["website_url"], "https://nearby.example.com")
        self.assertEqual(results[0]["link_url"], "https://nearby.example.com")
        # Dealer without a website falls back to its Maps listing
        self.assertEqual(results[1]["link_url"], "https://maps.google.com/?cid=2")
        self.assertLess(results[0]["distance_km"], results[1]["distance_km"])

    def test_out_of_radius_dealers_are_excluded(self, _m_analytics, m_places):
        dealers = ([
            {
                "displayName": {"text": "Distant City Motors"},
                "location": {"latitude": -37.81, "longitude": 144.96},  # Melbourne
                "googleMapsUri": "https://maps.google.com/?cid=3",
            },
        ], None)
        self._mock_places(m_places, [self.GEOCODE_RESPONSE, dealers])
        resp = self.client.post(
            reverse("find-dealer"),
            {"garage_vehicle_id": str(self.garage_vehicle.id),
             "postcode": "2000", "radius_km": 25},
            format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["results"], [])
        self.assertIn("no_results_message", resp.data)
        self.assertIn("TestMake", resp.data["no_results_message"])

    def test_spec_get_route_works_with_brand(self, _m_analytics, m_places):
        # Spec: GET /api/garage/find-a-dealer/?postcode=&radius=&brand=
        self._mock_places(m_places, [self.GEOCODE_RESPONSE, self.DEALERS_RESPONSE])
        resp = self.client.get(
            reverse("find-a-dealer"),
            {"postcode": "2000", "radius": 25, "brand": "TestMake"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 2)

    def test_spec_get_route_works_with_garage_vehicle(self, _m_analytics, m_places):
        self._mock_places(m_places, [self.GEOCODE_RESPONSE, self.DEALERS_RESPONSE])
        resp = self.client.get(
            reverse("find-a-dealer"),
            {"postcode": "2000", "radius": "25",
             "garage_vehicle_id": str(self.garage_vehicle.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["vehicle_brand"], "TestMake")

    def test_get_requires_brand_or_garage_vehicle(self, _m_analytics, m_places):
        resp = self.client.get(
            reverse("find-a-dealer"), {"postcode": "2000", "radius": 25})
        self.assertEqual(resp.status_code, 400)
        m_places.assert_not_called()

    def test_invalid_postcode_rejected(self, _m_analytics, m_places):
        resp = self.client.post(
            reverse("find-dealer"),
            {"garage_vehicle_id": str(self.garage_vehicle.id),
             "postcode": "0500", "radius_km": 25},
            format="json")
        self.assertEqual(resp.status_code, 422)
        m_places.assert_not_called()

    def test_foreign_garage_vehicle_is_not_found(self, _m_analytics, m_places):
        other = User.objects.create_user(email="other@example.com", password="x")
        gv = GarageVehicle.objects.create(
            user=other, vehicle_catalogue=self.vehicle,
            source=GarageVehicleSource.VEHICLE_LOOKUP,
        )
        resp = self.client.post(
            reverse("find-dealer"),
            {"garage_vehicle_id": str(gv.id),
             "postcode": "2000", "radius_km": 25},
            format="json")
        self.assertEqual(resp.status_code, 404)
        m_places.assert_not_called()

    def test_analytics_accepts_dealer_and_vehicle_payload(self, _m_analytics, _m_places):
        resp = self.client.post(
            reverse("dealer-link-clicked"),
            {"vehicle_brand": "TestMake",
             "dealer_name": "Nearby Motors",
             "vehicle_id": str(self.vehicle.id),
             "link_url": "https://nearby.example.com"},
            format="json")
        self.assertEqual(resp.status_code, 200)
