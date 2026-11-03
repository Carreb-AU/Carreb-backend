from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase as TestCase
from django.urls import reverse

from apps.vehicles.models import Vehicle
from apps.mygarage.models import GarageVehicle, GarageVehicleSource, RideRevealJob

User = get_user_model()


# Rating registry: survives queryset refetches inside the view (an instance
# attribute like v._test_rating would be lost when the view re-queries).
_TEST_RATINGS = {}


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
    _TEST_RATINGS[(v.brand, v.model, v.variant)] = rating
    return v


def rating_side_effect(vehicle=None, **kwargs):
    if vehicle is not None:
        driveaway = (vehicle.driveaway_price_by_state or {}).get("NSW") or 0
        rating = _TEST_RATINGS.get(
            (vehicle.brand, vehicle.model, vehicle.variant), 3.0)
    else:
        driveaway = 0
        rating = 3.0
    return {
        "core_rating": rating,
        "band_name": "Good",
        "total_annual_cost": driveaway,
        "est_cost_difference": None,
    }


@mock.patch("apps.mygarage.views.emit_analytics_event")
@mock.patch("apps.mygarage.views.calculate_core_rating", side_effect=rating_side_effect)
@mock.patch("apps.mygarage.views.extract_search_parameters",
            return_value=(True, {"make": "Mazda", "model": "CX-5"}))
@mock.patch("apps.mygarage.views.get_vehicle_image_url",
            return_value="https://img.example/fallback.jpg")
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

    def test_one_variant_per_model_cheapest_wins(self, *_mocks):
        make_vehicle(brand="Mazda", model="CX-5", variant="Maxx Sport",
                     driveaway_price_by_state={"NSW": 38_000_00}, rating=4.0)
        make_vehicle(brand="Mazda", model="CX-5", variant="GT",
                     driveaway_price_by_state={"NSW": 52_000_00}, rating=4.5)
        make_vehicle(brand="Mazda", model="CX-5", variant="Akera",
                     driveaway_price_by_state={"NSW": 65_000_00}, rating=5.0)
        res = self._post()
        cx5 = [r for r in res.json()["results"] if r["model"] == "CX-5"]
        self.assertEqual(len(cx5), 1)
        self.assertEqual(cx5[0]["variant"], "Maxx Sport")

    def test_variant_without_price_loses_to_priced_variant(self, *_mocks):
        make_vehicle(brand="Mazda", model="CX-5", variant="No Price",
                     driveaway_price_by_state={"NSW": None}, rating=5.0)
        make_vehicle(brand="Mazda", model="CX-5", variant="Priced",
                     driveaway_price_by_state={"NSW": 45_000_00}, rating=4.0)
        res = self._post()
        cx5 = [r for r in res.json()["results"] if r["model"] == "CX-5"]
        self.assertEqual(len(cx5), 1)
        self.assertEqual(cx5[0]["variant"], "Priced")

    def test_better_rated_trim_within_price_tolerance_wins(self, *_mocks):
        # Baseline $38k @ 4.0; $40k is within +10% and rates higher -> wins;
        # $52k rates highest but is beyond the tolerance -> stays excluded.
        make_vehicle(brand="Mazda", model="CX-5", variant="Base",
                     driveaway_price_by_state={"NSW": 38_000_00}, rating=4.0)
        make_vehicle(brand="Mazda", model="CX-5", variant="Smart Buy",
                     driveaway_price_by_state={"NSW": 40_000_00}, rating=4.6)
        make_vehicle(brand="Mazda", model="CX-5", variant="Flagship",
                     driveaway_price_by_state={"NSW": 52_000_00}, rating=5.0)
        res = self._post()
        cx5 = [r for r in res.json()["results"] if r["model"] == "CX-5"]
        self.assertEqual(len(cx5), 1)
        self.assertEqual(cx5[0]["variant"], "Smart Buy")
        self.assertEqual(cx5[0]["driveaway_price"], 40_000_00)

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

    def test_results_include_image_url(self, *_mocks):
        # Regression: results rendered without images because the response
        # never carried image_url.
        make_vehicle(brand="Mazda", model="CX-5", variant="Maxx",
                     image_url="/media/mazda-cx5.jpg")
        make_vehicle(brand="Mazda", model="CX-3", variant="Maxx")  # no stored image
        results = self._post().json()["results"]
        self.assertTrue(all("image_url" in r for r in results))
        by_model = {r["model"]: r for r in results}
        self.assertEqual(by_model["CX-5"]["image_url"], "/media/mazda-cx5.jpg")
        # No stored image -> lookup fallback is used
        self.assertEqual(by_model["CX-3"]["image_url"],
                         "https://img.example/fallback.jpg")

    def test_suppressed_listings_never_match(self, *_mocks):
        # Held listings (maker withheld pricing) must not appear in matches
        # or counts (B-12).
        make_vehicle(brand="Mazda", model="CX-5", variant="Held",
                     is_suppressed=True)
        res = self._post()
        self.assertEqual(res.status_code, 200)
        variants = [r["variant"] for r in res.json()["results"]]
        self.assertNotIn("Held", variants)


@mock.patch("apps.mygarage.views.get_vehicle_image_url", return_value="https://img.example/fallback.jpg")
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

@mock.patch("apps.mygarage.views.get_vehicle_image_url", return_value="https://img.example/fallback.jpg")

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
@mock.patch("apps.mygarage.views.get_vehicle_image_url", return_value="https://img.example/fallback.jpg")


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

    def test_radius_100km_clamps_bias_circle_but_keeps_true_radius(self, _m_analytics, m_places):
        # Google Places caps locationBias circle.radius at 50000 m; passing
        # 100000 m made every 100 km search fail with service_unavailable.
        # The bias is clamped, and the haversine filter must still apply the
        # real 100 km radius.
        dealers = ([
            {
                "displayName": {"text": "In Range Motors"},  # ~80 km north
                "location": {"latitude": -33.15, "longitude": 151.2093},
                "googleMapsUri": "https://maps.google.com/?cid=4",
            },
            {
                "displayName": {"text": "Too Far Motors"},  # ~150 km north
                "location": {"latitude": -32.52, "longitude": 151.2093},
                "googleMapsUri": "https://maps.google.com/?cid=5",
            },
        ], None)
        self._mock_places(m_places, [self.GEOCODE_RESPONSE, dealers])
        resp = self.client.post(
            reverse("find-dealer"),
            {"garage_vehicle_id": str(self.garage_vehicle.id),
             "postcode": "2000", "radius_km": 100},
            format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("service_unavailable", resp.data)
        payload = m_places.call_args_list[1][0][0]
        self.assertEqual(
            payload["locationBias"]["circle"]["radius"], 50000)
        names = [r["dealer_name"] for r in resp.data["results"]]
        self.assertEqual(names, ["In Range Motors"])

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


class GVGGarageVehicleTests(TestCase):
    """GVG (used/older) vehicles can be added to My Garage (Option A).

    Previously GarageVehicle only held a non-nullable catalogue FK, so GVG
    search results could be set as the current vehicle but never added to the
    garage. These tests pin the new behaviour.
    """

    def setUp(self):
        from apps.vehicles.models import VehicleIdentity, StateEnergyPrice
        self.user = User.objects.create_user(email="gvg@example.com", password="x")
        self.client.force_authenticate(self.user)
        self.gvg_record = VehicleIdentity.objects.create(
            make="Toyota", model="Corolla", year=2015,
            body_style="hatchback", fcai_category="Small",
            powertrain_type="petrol",
            fuel_consumption_combined_l_100km=6.1,
            tailpipe_co2_g_per_km=143.0,
        )
        StateEnergyPrice.objects.create(
            state="NSW", petrol_ulp95_cents_per_litre=240,
            diesel_cents_per_litre=280, electricity_cents_per_kwh=30.0,
        )

    def test_add_gvg_vehicle_to_garage(self):
        resp = self.client.post(
            reverse("garage-vehicles"),
            {"green_vehicle_guide_record_id": str(self.gvg_record.id),
             "source": "vehicle_lookup"},
            format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            str(resp.data["green_vehicle_guide_record_id"]), str(self.gvg_record.id))
        gv = GarageVehicle.objects.get(user=self.user)
        self.assertIsNone(gv.vehicle_catalogue_id)
        self.assertEqual(str(gv.green_vehicle_guide_record_id), str(self.gvg_record.id))

    def test_garage_list_includes_gvg_vehicle_with_costs(self):
        GarageVehicle.objects.create(
            user=self.user, green_vehicle_guide_record=self.gvg_record,
            source=GarageVehicleSource.VEHICLE_LOOKUP)
        resp = self.client.get(reverse("garage-vehicles"))
        self.assertEqual(resp.status_code, 200)
        vehicles = resp.data["vehicles"]
        self.assertEqual(len(vehicles), 1)
        card = vehicles[0]
        self.assertEqual(card["vehicle_data"]["source"], "gvg")
        self.assertEqual(card["vehicle_data"]["make"], "Toyota")
        self.assertEqual(card["vehicle_data"]["year"], 2015)
        # Used-car cost path: fixed medians + own consumption, no CORE rating.
        self.assertIsNotNone(card["engine_data"])
        self.assertIsNone(card["engine_data"]["core_rating"])
        self.assertGreater(card["engine_data"]["total_annual_cost"], 0)
        self.assertEqual(card["engine_data"]["tailpipe_co2_g_per_km"], 143.0)

    def test_both_ids_rejected(self):
        v = make_vehicle()
        resp = self.client.post(
            reverse("garage-vehicles"),
            {"vehicle_catalogue_id": str(v.id),
             "green_vehicle_guide_record_id": str(self.gvg_record.id),
             "source": "vehicle_lookup"},
            format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("non_field_errors", resp.data)

    def test_neither_id_rejected(self):
        resp = self.client.post(
            reverse("garage-vehicles"),
            {"source": "vehicle_lookup"},
            format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("non_field_errors", resp.data)

    def test_unknown_gvg_id_rejected(self):
        import uuid
        resp = self.client.post(
            reverse("garage-vehicles"),
            {"green_vehicle_guide_record_id": str(uuid.uuid4()),
             "source": "vehicle_lookup"},
            format="json")
        self.assertEqual(resp.status_code, 400)

    def test_current_vehicle_gvg_pick_auto_adds_to_garage(self):
        resp = self.client.post(
            reverse("current-vehicle"),
            {"green_vehicle_guide_record_id": str(self.gvg_record.id),
             "state": "NSW"},
            format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(GarageVehicle.objects.filter(
            user=self.user,
            green_vehicle_guide_record_id=self.gvg_record.id).exists())

    def test_current_vehicle_gvg_pick_does_not_duplicate_garage_row(self):
        GarageVehicle.objects.create(
            user=self.user, green_vehicle_guide_record=self.gvg_record,
            source=GarageVehicleSource.VEHICLE_LOOKUP)
        resp = self.client.post(
            reverse("current-vehicle"),
            {"green_vehicle_guide_record_id": str(self.gvg_record.id),
             "state": "NSW"},
            format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            GarageVehicle.objects.filter(
                user=self.user,
                green_vehicle_guide_record_id=self.gvg_record.id).count(), 1)

    def test_spotlights_endpoint_tolerates_gvg_garage_vehicle(self):
        from apps.users.models import SubscriptionTier
        self.user.subscription_tier = SubscriptionTier.CORE_ADVANTAGE
        self.user.save()
        GarageVehicle.objects.create(
            user=self.user, green_vehicle_guide_record=self.gvg_record,
            source=GarageVehicleSource.VEHICLE_LOOKUP)
        resp = self.client.get(reverse("spotlights"))
        self.assertEqual(resp.status_code, 200)
        gvg_gv = GarageVehicle.objects.get(user=self.user)
        # GVG rows appear in the result keyed by garage id but earn no badges.
        self.assertIn(str(gvg_gv.id), resp.data)
        self.assertEqual(resp.data[str(gvg_gv.id)], {})

    def test_ridereveal_rejects_gvg_garage_vehicle_cleanly(self):
        gv = GarageVehicle.objects.create(
            user=self.user, green_vehicle_guide_record=self.gvg_record,
            source=GarageVehicleSource.VEHICLE_LOOKUP)
        resp = self.client.post(
            reverse("ridereveal-generate"),
            {"garage_vehicle_id": str(gv.id)},
            format="json")
        self.assertEqual(resp.status_code, 422)

    def test_find_dealer_uses_gvg_make(self):
        gv = GarageVehicle.objects.create(
            user=self.user, green_vehicle_guide_record=self.gvg_record,
            source=GarageVehicleSource.VEHICLE_LOOKUP)
        from unittest import mock as _mock
        from apps.mygarage import find_dealer_views as fdv
        with _mock.patch.object(fdv, "get_dealers") as m_dealers, \
             _mock.patch("apps.mygarage.views.emit_analytics_event"):
            m_dealers.return_value = {"results": [], "service_unavailable": False}
            resp = self.client.get(
                reverse("find-a-dealer"),
                {"garage_vehicle_id": str(gv.id),
                 "postcode": "2000", "radius": "25"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(m_dealers.call_args[0][0], "Toyota")


class RideRevealFavoriteColorTests(TestCase):
    """Favorite color selected during RideReveal is captured and returned."""

    def setUp(self):
        from apps.users.models import SubscriptionTier
        self.user = User.objects.create_user(
            email="rr@example.com", password="x",
            subscription_tier=SubscriptionTier.FULL_INSIGHT_PRO)
        self.client.force_authenticate(self.user)
        self.vehicle = make_vehicle()
        self.gv = GarageVehicle.objects.create(
            user=self.user, vehicle_catalogue=self.vehicle,
            source=GarageVehicleSource.VEHICLE_LOOKUP)

    @mock.patch("apps.mygarage.tasks.generate_ridereveal_content")
    def test_generate_stores_favorite_color_on_job(self, m_task):
        resp = self.client.post(
            reverse("ridereveal-generate"),
            {"garage_vehicle_id": str(self.gv.id),
             "favorite_color": "Midnight Blue"}, format="json")
        self.assertEqual(resp.status_code, 200)
        job = RideRevealJob.objects.get(user=self.user)
        self.assertEqual(job.favorite_color, "Midnight Blue")
        m_task.delay.assert_called_once()

    @mock.patch("apps.mygarage.tasks.generate_ridereveal_content")
    def test_generate_without_color_stays_null(self, m_task):
        resp = self.client.post(
            reverse("ridereveal-generate"),
            {"garage_vehicle_id": str(self.gv.id)}, format="json")
        self.assertEqual(resp.status_code, 200)
        job = RideRevealJob.objects.get(user=self.user)
        self.assertIsNone(job.favorite_color)

    @mock.patch("apps.mygarage.tasks.generate_ridereveal_content")
    def test_generate_stores_first_name_on_job(self, m_task):
        resp = self.client.post(
            reverse("ridereveal-generate"),
            {"garage_vehicle_id": str(self.gv.id),
             "first_name": "Stephen"}, format="json")
        self.assertEqual(resp.status_code, 200)
        job = RideRevealJob.objects.get(user=self.user)
        self.assertEqual(job.first_name, "Stephen")
        m_task.delay.assert_called_once()

    def test_result_serializer_returns_first_name(self):
        from apps.mygarage.models import (
            RideRevealResult, RideRevealCreditType)
        from apps.mygarage.serializers import RideRevealResultSerializer
        result = RideRevealResult.objects.create(
            user=self.user, garage_vehicle=self.gv,
            vehicle_catalogue=self.vehicle,
            first_name="Stephen",
            archetype_name="Steady Optimist",
            archetype_tagline="Calm confidence",
            self_insight_text="x", social_perception_text="y",
            did_you_know_fact="z", share_caption="c",
            ai_model_version="gpt-4o-mini", generation_duration_ms=100,
            credit_type=RideRevealCreditType.PLAN_INCLUDED)
        data = RideRevealResultSerializer(result).data
        self.assertEqual(data["first_name"], "Stephen")

    def test_result_serializer_returns_favorite_color(self):
        from apps.mygarage.models import (
            RideRevealResult, RideRevealCreditType)
        from apps.mygarage.serializers import RideRevealResultSerializer
        result = RideRevealResult.objects.create(
            user=self.user, garage_vehicle=self.gv,
            vehicle_catalogue=self.vehicle,
            favorite_color="Midnight Blue",
            archetype_name="Steady Optimist",
            archetype_tagline="Calm confidence",
            self_insight_text="x", social_perception_text="y",
            did_you_know_fact="z", share_caption="c",
            ai_model_version="gpt-4o-mini", generation_duration_ms=100,
            credit_type=RideRevealCreditType.PLAN_INCLUDED)
        data = RideRevealResultSerializer(result).data
        self.assertEqual(data["favorite_color"], "Midnight Blue")


class RideRevealShareCardTests(TestCase):
    """Share-card context, HTML render, and share_image_url exposure."""

    def setUp(self):
        from apps.users.models import SubscriptionTier
        self.user = User.objects.create_user(
            email="rrshare@example.com", password="x", first_name="Ali",
            subscription_tier=SubscriptionTier.FULL_INSIGHT_PRO)
        self.client.force_authenticate(self.user)
        self.vehicle = make_vehicle(image_url="/media/vehicle_images/x.png")
        self.gv = GarageVehicle.objects.create(
            user=self.user, vehicle_catalogue=self.vehicle,
            source=GarageVehicleSource.VEHICLE_LOOKUP)
        from apps.mygarage.models import RideRevealCreditType
        from apps.mygarage.models import RideRevealResult
        self.result = RideRevealResult.objects.create(
            user=self.user, garage_vehicle=self.gv,
            vehicle_catalogue=self.vehicle,
            custom_plate="WE323", favorite_color="Midnight Blue",
            archetype_name="Steady Optimist",
            archetype_tagline="Calm confidence",
            self_insight_text="You choose well.",
            social_perception_text="Others notice.",
            did_you_know_fact="Rare company.",
            share_caption="c", ai_model_version="gpt-4o-mini",
            generation_duration_ms=100,
            credit_type=RideRevealCreditType.PLAN_INCLUDED)

    def test_context_maps_result_fields(self):
        from apps.mygarage.share_card import build_share_card_context
        ctx = build_share_card_context(self.result)
        self.assertEqual(ctx["display_name"], "Ali")
        self.assertEqual(ctx["avatar_initial"], "A")
        self.assertEqual(ctx["license_plate"], "WE323")
        self.assertEqual(ctx["favorite_color_label"], "Midnight Blue")
        self.assertEqual(ctx["favorite_color_hex"], "#1a2744")
        self.assertTrue(ctx["vehicle_image_url"].startswith("http"))
        self.assertEqual(ctx["traits"], [])

    def test_context_prefers_result_first_name_over_profile(self):
        from apps.mygarage.share_card import build_share_card_context
        self.result.first_name = "Stephen"
        ctx = build_share_card_context(self.result)
        self.assertEqual(ctx["display_name"], "Stephen")
        self.assertEqual(ctx["avatar_initial"], "S")

    def test_context_color_without_known_name_has_no_hex(self):
        from apps.mygarage.share_card import build_share_card_context
        self.result.favorite_color = "Sparkle Unicorn"
        ctx = build_share_card_context(self.result)
        self.assertEqual(ctx["favorite_color_hex"], "")

    def test_rendered_html_contains_card_content(self):
        from apps.mygarage.share_card import render_share_card_html
        html = render_share_card_html(self.result)
        self.assertIn('class="card"', html)
        self.assertIn("Steady Optimist", html)
        self.assertIn("WE323", html)
        self.assertIn("Midnight Blue", html)
        # user has no profile photo -> avatar fallback initial is rendered
        self.assertIn('class="avatar-fallback"', html)
        self.assertIn(">A<", html)

    def test_serializer_share_image_url_null_then_set(self):
        from apps.mygarage.serializers import RideRevealResultSerializer
        from django.core.files.base import ContentFile
        data = RideRevealResultSerializer(self.result).data
        self.assertIsNone(data["share_image_url"])
        self.result.share_image.save(
            f"{self.result.id}.png", ContentFile(b"png"), save=True)
        data = RideRevealResultSerializer(self.result).data
        self.assertTrue(data["share_image_url"].startswith("http"))


class CurrentVehicleSearchAIFallbackTests(TestCase):
    """DB search falls back to the Grok (AI) lookup only when the vehicle
    is genuinely absent from both the catalogue and GVG."""

    ENDPOINT = reverse("current-vehicle-search")

    def _ai_entry(self, **kwargs):
        from apps.vehicles.models import AIVehicleEntry
        defaults = dict(
            search_query="toyota camry 2015", make="Toyota", model="Camry",
            year=2015, variant="Atara S", body_style="sedan",
            powertrain_type="petrol",
            fuel_consumption_combined_l_100km=7.8,
            tailpipe_co2_g_per_km=181, fcai_category="Medium")
        defaults.update(kwargs)
        return AIVehicleEntry.objects.create(**defaults)

    @mock.patch("apps.mygarage.views.search_ai_vehicles")
    def test_db_match_never_calls_ai(self, m_ai):
        make_vehicle(brand="Toyota", model="Camry")
        resp = self.client.post(self.ENDPOINT,
                                {"query": "toyota camry"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(r["source"] == "carreb" for r in resp.data))
        m_ai.assert_not_called()

    @mock.patch("apps.mygarage.views.get_vehicle_image_url",
                 return_value="https://img.example/camry.jpg")
    @mock.patch("apps.mygarage.views.search_ai_vehicles")
    def test_missing_vehicle_falls_back_to_ai(self, m_ai, _img):
        m_ai.return_value = ([self._ai_entry()], False)
        resp = self.client.post(self.ENDPOINT,
                                {"query": "toyota camry 2015"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        row = resp.data[0]
        self.assertEqual(row["source"], "ai")
        self.assertEqual(row["make"], "Toyota")
        self.assertEqual(row["model"], "Camry")
        self.assertEqual(row["year"], 2015)
        self.assertEqual(row["fuel_consumption_per_100km"], 7.8)
        self.assertEqual(row["tailpipe_co2_g_per_km"], 181)

    @mock.patch("apps.mygarage.views.search_ai_vehicles")
    def test_ai_failure_keeps_db_results(self, m_ai):
        from apps.vehicles.services.ai_vehicle_search import AIVehicleSearchError
        m_ai.side_effect = AIVehicleSearchError("AI lookup failed")
        resp = self.client.post(self.ENDPOINT,
                                {"query": "toyota camry 2015"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    @mock.patch("apps.mygarage.views.search_ai_vehicles")
    def test_single_word_fragment_never_calls_ai(self, m_ai):
        resp = self.client.post(self.ENDPOINT, {"query": "camry"}, format="json")
        self.assertEqual(resp.status_code, 200)
        m_ai.assert_not_called()

    @mock.patch("apps.mygarage.views.search_ai_vehicles")
    def test_variant_word_matches_catalogue_row(self, m_ai):
        """Vehicle Lookup sends the picked trim (e.g. 'Bentayga Azure');
        the trim word must match the variant field so a real catalogue row
        is returned instead of falling through to the AI fallback."""
        make_vehicle(brand="Bentley", model="Bentayga",
                     variant="Bentayga Azure", year=2026)
        resp = self.client.post(self.ENDPOINT,
                                {"query": "2026 Bentley Bentayga Azure"},
                                format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(r["source"] == "carreb" for r in resp.data))

    @mock.patch("apps.mygarage.views.search_ai_vehicles")
    def test_suppressed_listing_never_returned(self, m_ai):
        # Held listings (B-12) are invisible to vehicle search; the query
        # falls through to the AI path like any absent vehicle.
        make_vehicle(brand="Aston Martin", model="Vantage",
                     is_suppressed=True)
        m_ai.return_value = ([], False)
        resp = self.client.post(self.ENDPOINT,
                                {"query": "aston martin vantage"},
                                format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(any(r["source"] == "carreb" for r in resp.data))

    @mock.patch("apps.mygarage.views.get_vehicle_image_url",
                 return_value="https://img.example/fallback.jpg")
    @mock.patch("apps.mygarage.views.search_ai_vehicles")
    def test_ai_appended_after_db_rows_never_replaces(self, m_ai, _img):
        """AI guesses are appended after DB rows, not swapped in. When the
        DB returns loose rows (prod GVG trigram matches) and no row covers
        every query word, the real catalogue row must still lead the list
        with any AI card behind it."""
        make_vehicle(brand="Bentley", model="Bentayga",
                     variant="Bentayga V8", year=2026)
        from apps.mygarage.views import CurrentVehicleSearchView
        m_ai.return_value = ([self._ai_entry(
            search_query="2026 bentley bentayga azure",
            make="Bentley", model="Bentayga", year=2026,
            variant="Bentayga Azure")], False)
        with mock.patch.object(CurrentVehicleSearchView, "_strict_matches",
                               return_value=False):
            resp = self.client.post(
                self.ENDPOINT, {"query": "2026 Bentley Bentayga V8"},
                format="json")
        self.assertEqual(resp.status_code, 200)
        sources = [r["source"] for r in resp.data]
        self.assertEqual(sources[0], "carreb")
        self.assertIn("ai", sources)
        self.assertLess(sources.index("carreb"), sources.index("ai"))


class GarageAddAIEntryTests(TestCase):
    """Garage accepts AIVehicleEntry rows (cars missing from catalogue+GVG)."""

    def setUp(self):
        from apps.users.models import SubscriptionTier
        self.user = User.objects.create_user(
            email="aigarage@example.com", password="x",
            subscription_tier=SubscriptionTier.FULL_INSIGHT_PRO)
        self.client.force_authenticate(self.user)
        from apps.vehicles.models import AIVehicleEntry
        self.ai_entry = AIVehicleEntry.objects.create(
            search_query="toyota camry 2015", make="Toyota", model="Camry",
            year=2015, variant="Atara S", body_style="sedan",
            powertrain_type="petrol", fuel_consumption_combined_l_100km=7.8,
            tailpipe_co2_g_per_km=181, fcai_category="Medium")

    def test_add_ai_entry_to_garage(self):
        resp = self.client.post(
            reverse("garage-vehicles"),
            {"ai_vehicle_entry_id": str(self.ai_entry.id),
             "source": "vehicle_lookup"}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(str(resp.data["ai_vehicle_entry_id"]), str(self.ai_entry.id))
        self.assertIsNone(resp.data["vehicle_catalogue_id"])

    def test_add_rejects_two_id_fields(self):
        v = make_vehicle()
        resp = self.client.post(
            reverse("garage-vehicles"),
            {"vehicle_catalogue_id": str(v.id),
             "ai_vehicle_entry_id": str(self.ai_entry.id),
             "source": "vehicle_lookup"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_ai_id_in_catalogue_field_is_routed(self):
        """Frontend that always sends the result id as vehicle_catalogue_id
        still works when the result was an AI vehicle."""
        resp = self.client.post(
            reverse("garage-vehicles"),
            {"vehicle_catalogue_id": str(self.ai_entry.id),
             "source": "vehicle_lookup"}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(str(resp.data["ai_vehicle_entry_id"]), str(self.ai_entry.id))
        self.assertIsNone(resp.data["vehicle_catalogue_id"])
        gv = GarageVehicle.objects.get(user=self.user)
        self.assertEqual(str(gv.ai_vehicle_entry_id), str(self.ai_entry.id))

    def test_ai_garage_card_surfaces_full_spec(self):
        """AI garage cards must not come back half-empty: drive, engine_l,
        seats, ANCAP and an image fallback all appear in vehicle_data."""
        self.ai_entry.drive = "FWD"
        self.ai_entry.engine_l = 2.5
        self.ai_entry.num_seats = 5
        self.ai_entry.ancap_safety_rating = 5
        self.ai_entry.save()
        self.client.post(
            reverse("garage-vehicles"),
            {"ai_vehicle_entry_id": str(self.ai_entry.id),
             "source": "vehicle_lookup"}, format="json")
        resp = self.client.get(reverse("garage-vehicles"))
        card = resp.data["vehicles"][0]
        vd = card["vehicle_data"]
        self.assertEqual(vd["drive"], "FWD")
        self.assertEqual(vd["engine_l"], 2.5)
        self.assertEqual(vd["num_seats"], 5)
        self.assertEqual(vd["ancap_safety_rating"], 5)

    def test_current_vehicle_with_ai_entry_creates_garage_row(self):
        resp = self.client.post(
            reverse("current-vehicle"),
            {"ai_vehicle_entry_id": str(self.ai_entry.id),
             "state": "NSW"}, format="json")
        self.assertEqual(resp.status_code, 200)
        gv = GarageVehicle.objects.get(user=self.user)
        self.assertEqual(str(gv.ai_vehicle_entry_id), str(self.ai_entry.id))
        self.assertEqual(resp.data["vehicle_data"]["source"], "ai")
        self.assertEqual(resp.data["vehicle_data"]["make"], "Toyota")


class FirstGarageAddSetsCurrentVehicleTests(TestCase):
    """First vehicle added to the garage becomes the current vehicle."""

    def setUp(self):
        from apps.users.models import SubscriptionTier
        self.user = User.objects.create_user(
            email="firstadd@example.com", password="x",
            subscription_tier=SubscriptionTier.FULL_INSIGHT_PRO)
        self.client.force_authenticate(self.user)

    def test_first_garage_add_sets_current_vehicle(self):
        v = make_vehicle()
        resp = self.client.post(
            reverse("garage-vehicles"),
            {"vehicle_catalogue_id": str(v.id), "source": "vehicle_lookup"},
            format="json")
        self.assertEqual(resp.status_code, 201)
        cv = self.user.current_vehicle
        self.assertEqual(str(cv.vehicle_catalogue_id), str(v.id))

    def test_second_garage_add_does_not_overwrite(self):
        v1 = make_vehicle()
        self.client.post(
            reverse("garage-vehicles"),
            {"vehicle_catalogue_id": str(v1.id), "source": "vehicle_lookup"},
            format="json")
        v2 = make_vehicle(brand="Subaru")
        self.client.post(
            reverse("garage-vehicles"),
            {"vehicle_catalogue_id": str(v2.id), "source": "vehicle_lookup"},
            format="json")
        cv = self.user.current_vehicle
        self.assertEqual(str(cv.vehicle_catalogue_id), str(v1.id))


class CurrentVehicleStateFallbackTests(TestCase):
    """Current vehicle with no saved state (no priority_state.state, no
    cv.state) must still show figures — NSW fallback, flagged in meta —
    instead of an empty engine_data ('—' on every cost row)."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="nostate@example.com", password="x")
        self.client.force_authenticate(self.user)

    def _set_cv(self, **cv_kwargs):
        v = make_vehicle()
        payload = {"vehicle_catalogue_id": str(v.id)}
        payload.update(cv_kwargs)
        resp = self.client.post(reverse("current-vehicle"), payload,
                                format="json")
        self.assertEqual(resp.status_code, 200)
        return v

    @mock.patch("apps.mygarage.views.calculate_core_rating")
    def test_no_state_falls_back_to_nsw(self, m_calc):
        m_calc.return_value = {"core_rating": 2.0, "total_annual_cost": 599100}
        self._set_cv()
        resp = self.client.get(reverse("current-vehicle"))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.data["engine_data"])
        self.assertEqual(
            resp.data["engine_data"]["total_annual_cost"], 599100)
        self.assertEqual(resp.data["meta"]["state"], "NSW")
        self.assertTrue(resp.data["meta"]["state_defaulted"])

    @mock.patch("apps.mygarage.views.calculate_core_rating")
    def test_saved_state_used_and_not_defaulted(self, m_calc):
        m_calc.return_value = {"core_rating": 2.0, "total_annual_cost": 599100}
        self._set_cv(state="QLD")
        resp = self.client.get(reverse("current-vehicle"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["meta"]["state"], "QLD")
        self.assertFalse(resp.data["meta"]["state_defaulted"])
        self.assertEqual(m_calc.call_args[0][1], "QLD")


class SameModeCostDifferenceTests(TestCase):
    """B-13: the current vehicle must be costed in the user's selected CORE
    mode so garage-card cost differences compare like with like (previously
    the CV was always Pure Cost while cards used the selected mode)."""

    MODE_COSTS = {
        "pure_cost": 599100,
        "cool_choice": 800100,
        "true_value": 4824100,
        "full_picture": 510100,
    }

    def setUp(self):
        from apps.mygarage.models import UserPriorityState
        self.user = User.objects.create_user(
            email="modes@example.com", password="x")
        UserPriorityState.objects.create(
            user=self.user, state="NSW", priority_slider_position=4,
            active_core_mode="true_value")
        self.client.force_authenticate(self.user)
        self.cv_vehicle = make_vehicle(brand="Mazda", model="CX-5")
        self.garage_vehicle = make_vehicle(brand="Audi", model="Q5")

    @mock.patch("apps.mygarage.views.calculate_core_rating")
    def test_cv_costed_in_active_mode_with_all_mode_costs(self, m_calc):
        recorded = []
        m_calc.side_effect = lambda vehicle=None, *a, **k: (
            recorded.append({"mode": a[2] if len(a) > 2 else None,
                             "current_cost": k.get("current_vehicle_annual_cost")}),
            {"core_rating": 3.0,
             "total_annual_cost": self.MODE_COSTS[a[2]],
             "est_cost_difference": None})[1]
        self.client.post(reverse("current-vehicle"),
                         {"vehicle_catalogue_id": str(self.cv_vehicle.id)},
                         format="json")
        resp = self.client.get(reverse("current-vehicle"))
        self.assertEqual(resp.status_code, 200)
        # Headline cost is the ACTIVE mode (true_value), not Pure Cost.
        self.assertEqual(resp.data["engine_data"]["total_annual_cost"],
                         self.MODE_COSTS["true_value"])
        # All four modes exposed for same-mode comparisons.
        self.assertEqual(resp.data["engine_data"]["mode_annual_costs"],
                         self.MODE_COSTS)
        self.assertEqual(recorded[0]["mode"], "true_value")

    @mock.patch("apps.mygarage.views.calculate_core_rating")
    def test_garage_diff_uses_same_mode_cv_cost(self, m_calc):
        recorded = []
        m_calc.side_effect = lambda vehicle=None, *a, **k: (
            recorded.append({"mode": a[2] if len(a) > 2 else None,
                             "current_cost": k.get("current_vehicle_annual_cost")}),
            {"core_rating": 3.0,
             "total_annual_cost": self.MODE_COSTS[a[2]],
             "est_cost_difference": None})[1]
        self.client.post(reverse("current-vehicle"),
                         {"vehicle_catalogue_id": str(self.cv_vehicle.id)},
                         format="json")
        self.client.post(reverse("garage-vehicles"),
                         {"vehicle_catalogue_id": str(self.garage_vehicle.id),
                          "source": "vehicle_lookup"}, format="json")
        resp = self.client.get(reverse("garage-vehicles"))
        self.assertEqual(resp.status_code, 200)
        # Every comparison call must be costed in the user's mode AND
        # compared against the CV costed in that same mode (never Pure Cost).
        card_calls = [r for r in recorded if r["current_cost"] is not None]
        self.assertTrue(card_calls)
        for call in card_calls:
            self.assertEqual(call["mode"], "true_value")
            self.assertEqual(call["current_cost"],
                             self.MODE_COSTS["true_value"])


class GarageAddDedupeTests(TestCase):
    """Re-adding a vehicle that is already in the garage must not duplicate."""

    def setUp(self):
        from apps.users.models import SubscriptionTier
        self.user = User.objects.create_user(
            email="dedupe@example.com", password="x",
            subscription_tier=SubscriptionTier.FULL_INSIGHT_PRO)
        self.client.force_authenticate(self.user)
        self.vehicle = make_vehicle(image_url="/media/vehicle_images/dedupe.png")

    def test_second_add_returns_existing_row(self):
        body = {"vehicle_catalogue_id": str(self.vehicle.id),
                "source": "vehicle_lookup"}
        r1 = self.client.post(reverse("garage-vehicles"), body, format="json")
        self.assertEqual(r1.status_code, 201)
        r2 = self.client.post(reverse("garage-vehicles"), body, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.data["already_in_garage"])
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.assertEqual(GarageVehicle.objects.filter(user=self.user).count(), 1)


class FreeRideRevealEntitlementTests(TestCase):
    """Free-tier users get exactly one free RideReveal, consumed on use and
    refunded when generation fails; race-safe via row locking."""

    def setUp(self):
        from apps.users.models import SubscriptionTier
        self.user = User.objects.create_user(
            email="freereveal@example.com", password="x",
            subscription_tier=SubscriptionTier.FREE)
        self.client.force_authenticate(self.user)
        self.vehicle = make_vehicle(image_url="/media/vehicle_images/rr.png")
        self.gv = GarageVehicle.objects.create(
            user=self.user, vehicle_catalogue=self.vehicle,
            source=GarageVehicleSource.SMART_CAR_FINDER)

    def _generate(self):
        return self.client.post(
            reverse("ridereveal-generate"),
            {"garage_vehicle_id": str(self.gv.id)}, format="json")

    def test_credits_endpoint_advertises_free_reveal(self):
        resp = self.client.get(reverse("ridereveal-credits"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["free_reveal_available"])
        self.assertFalse(resp.data["free_reveal_used"])

    @mock.patch("apps.mygarage.tasks.generate_ridereveal_content")
    def test_free_user_generates_with_free_signup_credit(self, task):
        from apps.mygarage.models import RideRevealCredit
        resp = self._generate()
        self.assertEqual(resp.status_code, 200)
        args, _ = task.delay.call_args
        self.assertEqual(args[1], "free_signup")
        # Query fresh: the create path caches a stale instance on the user.
        credit = RideRevealCredit.objects.get(user=self.user)
        self.assertTrue(credit.free_reveal_used)
        self.assertEqual(credit.credits_used, 0)  # counters untouched

        # Entitlement is consumed — a second attempt hits the paywall.
        resp2 = self._generate()
        self.assertEqual(resp2.status_code, 402)
        task.delay.assert_called_once()

        # Still consumed after logout/login (same DB row).
        credit.refresh_from_db()
        self.assertTrue(credit.free_reveal_used)
        resp3 = self.client.get(reverse("ridereveal-credits"))
        self.assertFalse(resp3.data["free_reveal_available"])

    @mock.patch("apps.mygarage.tasks.generate_ridereveal_content")
    def test_paid_user_flow_unaffected(self, task):
        from apps.users.models import SubscriptionTier
        self.user.subscription_tier = SubscriptionTier.CAR_BUYING_SPRINT
        self.user.save()
        resp = self._generate()
        self.assertEqual(resp.status_code, 200)
        args, _ = task.delay.call_args
        self.assertEqual(args[1], "plan_included")

    def test_failed_generation_refunds_free_entitlement(self):
        """A failed reveal must give the free entitlement back."""
        from apps.mygarage import tasks as rr_tasks
        from apps.mygarage.models import (
            RideRevealCredit, RideRevealJob, RideRevealJobStatus,
        )

        with mock.patch("apps.mygarage.tasks.generate_ridereveal_content") as svc_task:
            resp = self._generate()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            RideRevealCredit.objects.get(user=self.user).free_reveal_used)

        job = RideRevealJob.objects.get(user=self.user)
        with mock.patch.object(rr_tasks.openai, "OpenAI") as openai_cls:
            openai_cls.side_effect = Exception("AI provider down")
            rr_tasks.generate_ridereveal_content(job.id, "free_signup")

        job.refresh_from_db()
        self.assertEqual(job.status, RideRevealJobStatus.FAILED)
        credit = RideRevealCredit.objects.get(user=self.user)
        self.assertFalse(credit.free_reveal_used)
        self.assertEqual(credit.credits_used, 0)


class GarageCapCounterTests(TestCase):
    """Archived vehicles are hidden history: they must NOT count against the
    plan vehicle cap. A Full Insight user at 26 active + 4 archived was
    seeing 'used 30/30' and an upgrade prompt on every add."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = User.objects.create_user(
            email="cap@example.com", password="x",
            subscription_tier="full_insight_pro")
        self.client.force_authenticate(self.user)
        self.vehicle = make_vehicle(brand="CapMake")

    def _add(self, i):
        return GarageVehicle.objects.create(
            user=self.user, vehicle_catalogue=self.vehicle,
            source=GarageVehicleSource.VEHICLE_LOOKUP)

    def test_cap_counts_active_only(self):
        from apps.mygarage.services import check_cap_limit, get_cap_counter
        for _ in range(3):
            self._add(0)
        gv = self._add(0)
        gv.status = "archived"
        gv.save(update_fields=["status"])
        cap = get_cap_counter(self.user)
        self.assertEqual(cap["used"], 3)
        self.assertEqual(cap["limit"], 30)
        self.assertTrue(check_cap_limit(self.user))

    def test_free_plan_allows_five_vehicles(self):
        """Agreed Free plan: 1 current vehicle + up to 5 vehicles in My
        Garage (the current vehicle occupies one garage slot). Regression:
        the cap was 1, so a free user who set their current vehicle was
        blocked from adding any other vehicle."""
        free_user = User.objects.create_user(
            email="freecap@example.com", password="x",
            subscription_tier="free")
        from apps.mygarage.services import check_cap_limit, get_cap_counter
        self.assertEqual(get_cap_counter(free_user)["limit"], 5)
        for i in range(4):
            GarageVehicle.objects.create(
                user=free_user, vehicle_catalogue=self.vehicle,
                source=GarageVehicleSource.VEHICLE_LOOKUP)
            self.assertTrue(check_cap_limit(free_user),
                            f"add #{i + 1} should be allowed")
        GarageVehicle.objects.create(
            user=free_user, vehicle_catalogue=self.vehicle,
            source=GarageVehicleSource.VEHICLE_LOOKUP)
        self.assertEqual(get_cap_counter(free_user)["used"], 5)
        self.assertFalse(check_cap_limit(free_user))

    def test_garage_list_counter_ignores_archived(self):
        for _ in range(2):
            self._add(0)
        gv = self._add(0)
        gv.status = "archived"
        gv.save(update_fields=["status"])
        resp = self.client.get(reverse("garage-vehicles"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["cap_counter"]["used"], 2)
