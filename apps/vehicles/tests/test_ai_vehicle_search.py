from unittest import mock

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.users.models import User
from apps.vehicles.models import AIVehicleEntry, PowertrainType
from apps.vehicles.services.ai_vehicle_search import (
    AIVehicleSearchError,
    _normalize_candidate,
    normalize_query,
    search_ai_vehicles,
)

FAKE_GROK_RESPONSE = {
    "vehicles": [
        {
            "year": 2015, "make": "Mazda", "model": "3", "variant": "Neo",
            "body_style": "sedan", "powertrain": "petrol",
            "fuel_type_raw": "Unleaded Petrol", "drive": "FWD",
            "engine_l": 2.0, "battery_kwh": None, "num_seats": 5,
            "ancap_safety_rating": 5, "fuel_consumption_l_100km": 6.4,
            "electricity_consumption_wh_per_km": None, "electric_range_km": None,
            "tailpipe_co2_g_per_km": 149.0, "driveaway_price_aud": 24500,
        },
        {
            "year": 2015, "make": "Mazda", "model": "3", "variant": "SP25",
            "body_style": "sedan", "powertrain": "petrol",
            "fuel_type_raw": "Unleaded Petrol", "drive": "FWD",
            "engine_l": 2.5, "battery_kwh": None, "num_seats": 5,
            "ancap_safety_rating": 5, "fuel_consumption_l_100km": 6.9,
            "electricity_consumption_wh_per_km": None, "electric_range_km": None,
            "tailpipe_co2_g_per_km": 161.0, "driveaway_price_aud": 28500,
        },
    ]
}


def _fake_fetch(query):
    return [_normalize_candidate(v, FAKE_GROK_RESPONSE) for v in FAKE_GROK_RESPONSE["vehicles"]]


class AIVehicleSearchServiceTests(TestCase):
    """The Grok-backed search stores candidates and serves repeats from cache."""

    @mock.patch(
        "apps.vehicles.services.ai_vehicle_search._fetch_from_grok",
        side_effect=_fake_fetch,
    )
    def test_first_search_calls_grok_and_stores_candidates(self, fetch_mock):
        entries, from_cache = search_ai_vehicles("2015 Mazda 3 Neo")

        self.assertFalse(from_cache)
        self.assertEqual(len(entries), 2)
        self.assertEqual(fetch_mock.call_count, 1)
        self.assertEqual(AIVehicleEntry.objects.count(), 2)

        first = entries[0]
        self.assertEqual(first.make, "Mazda")
        self.assertEqual(first.model, "3")
        self.assertEqual(first.year, 2015)
        self.assertEqual(first.powertrain_type, PowertrainType.PETROL)
        self.assertEqual(first.fuel_consumption_combined_l_100km, 6.4)
        self.assertEqual(first.tailpipe_co2_g_per_km, 149.0)
        self.assertEqual(first.driveaway_price_estimate, 2450000)  # cents
        self.assertEqual(first.search_query, "2015 mazda 3 neo")
        self.assertEqual(first.search_count, 1)

    @mock.patch(
        "apps.vehicles.services.ai_vehicle_search._fetch_from_grok",
        side_effect=_fake_fetch,
    )
    def test_repeat_search_is_served_from_cache_without_grok(self, fetch_mock):
        search_ai_vehicles("2015 Mazda 3 Neo")
        entries, from_cache = search_ai_vehicles("  2015   Mazda   3 Neo  ")

        self.assertTrue(from_cache)
        self.assertEqual(fetch_mock.call_count, 1)  # Grok billed exactly once
        self.assertEqual(len(entries), 2)
        self.assertEqual(AIVehicleEntry.objects.count(), 2)  # no duplicate rows
        self.assertEqual(entries[0].search_count, 2)  # usage still tracked

    @mock.patch(
        "apps.vehicles.services.ai_vehicle_search._fetch_from_grok",
        side_effect=AIVehicleSearchError("AI lookup failed: no credits"),
    )
    def test_grok_failure_raises_search_error(self, _mock):
        with self.assertRaises(AIVehicleSearchError):
            search_ai_vehicles("Something obscure")
        self.assertEqual(AIVehicleEntry.objects.count(), 0)

    def test_short_query_rejected(self):
        with self.assertRaises(AIVehicleSearchError):
            search_ai_vehicles("ab")

    def test_powertrain_mapping(self):
        cases = {
            "PHEV": PowertrainType.PHEV,
            "Plug-in Hybrid": PowertrainType.PHEV,
            "Electric": PowertrainType.BEV,
            "BEV": PowertrainType.BEV,
            "Diesel": PowertrainType.DIESEL,
            "Mild Hybrid": PowertrainType.MILD_HYBRID,
            "Hydrogen": PowertrainType.FCEV,
            "": PowertrainType.PETROL,
        }
        for raw, expected in cases.items():
            got = _normalize_candidate(
                {"make": "X", "model": "Y", "powertrain": raw}, {}
            )["powertrain_type"]
            self.assertEqual(got, expected, f"powertrain {raw!r}")

    def test_normalize_query(self):
        self.assertEqual(normalize_query("  2015   Mazda\t3  "), "2015 mazda 3")


class AIVehicleSearchAPITests(TestCase):
    """POST /api/current-vehicle/ai-search/ — auth required, caches, serializes."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="paid@example.com", password="x",
            subscription_tier="core_advantage")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("current-vehicle-ai-search")

    @mock.patch(
        "apps.vehicles.services.ai_vehicle_search._fetch_from_grok",
        side_effect=_fake_fetch,
    )
    def test_authenticated_search_returns_candidates(self, _mock):
        res = self.client.post(self.url, {"query": "2015 Mazda 3 Neo"}, format="json")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ai_available"])
        self.assertFalse(data["from_cache"])
        self.assertEqual(len(data["results"]), 2)
        first = data["results"][0]
        self.assertEqual(first["source"], "ai")
        self.assertEqual(first["name"], "2015 Mazda 3 Neo")
        self.assertEqual(first["driveaway_price_display"], "$24,500")
        self.assertEqual(first["tailpipe_co2_g_per_km"], 149.0)

    @mock.patch(
        "apps.vehicles.services.ai_vehicle_search._fetch_from_grok",
        side_effect=_fake_fetch,
    )
    def test_second_identical_request_uses_cache(self, fetch_mock):
        self.client.post(self.url, {"query": "2015 Mazda 3 Neo"}, format="json")
        res = self.client.post(self.url, {"query": "2015 Mazda 3 Neo"}, format="json")
        self.assertTrue(res.json()["from_cache"])
        self.assertEqual(fetch_mock.call_count, 1)

    def test_requires_authentication(self):
        anon = APIClient()
        res = anon.post(self.url, {"query": "Mazda 3"}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_short_query_rejected(self):
        res = self.client.post(self.url, {"query": "ab"}, format="json")
        self.assertEqual(res.status_code, 400)

    @mock.patch(
        "apps.vehicles.services.ai_vehicle_search._fetch_from_grok",
        side_effect=AIVehicleSearchError("AI lookup failed: no credits"),
    )
    def test_grok_failure_returns_502(self, _mock):
        res = self.client.post(self.url, {"query": "Something obscure"}, format="json")
        self.assertEqual(res.status_code, 502)
        self.assertFalse(res.json()["ai_available"])


class AIVehicleCurrentVehicleAPITests(TestCase):
    """Selecting an AI candidate as the current vehicle links + counts it."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="paid@example.com", password="x",
            subscription_tier="core_advantage")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.entry = AIVehicleEntry.objects.create(
            search_query="2015 mazda 3 neo",
            make="Mazda", model="3", year=2015, variant="Neo",
            body_style="sedan", powertrain_type=PowertrainType.PETROL,
            fuel_consumption_combined_l_100km=6.4,
            tailpipe_co2_g_per_km=149.0,
            fcai_category="Small", driveaway_price_estimate=2450000,
        )
        self.url = reverse("current-vehicle")

    def test_select_ai_entry_as_current_vehicle(self):
        res = self.client.post(self.url, {
            "ai_vehicle_entry_id": str(self.entry.id),
            "state": "NSW",
        }, format="json")
        self.assertEqual(res.status_code, 200)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.selected_count, 1)

        data = res.json()
        vehicle_data = data["vehicle_data"]
        self.assertEqual(vehicle_data["source"], "ai")
        self.assertEqual(vehicle_data["make"], "Mazda")
        self.assertEqual(vehicle_data["model"], "3")
        self.assertEqual(vehicle_data["tailpipe_co2_g_per_km"], 149.0)
        self.assertIn("total_annual_cost", data["engine_data"])

    def test_mutually_exclusive_with_catalogue_id(self):
        import uuid
        res = self.client.post(self.url, {
            "ai_vehicle_entry_id": str(self.entry.id),
            "vehicle_catalogue_id": str(uuid.uuid4()),
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_unknown_entry_id_rejected(self):
        import uuid
        res = self.client.post(self.url, {
            "ai_vehicle_entry_id": str(uuid.uuid4()),
        }, format="json")
        self.assertEqual(res.status_code, 400)
