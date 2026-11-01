"""Polymorphic /api/vehicles/<id>/ endpoint.

Carreb ids keep the ORM-serializer response; GVG (VehicleIdentity) and AI
(AIVehicleEntry) ids must return a catalogue-shaped payload with the
frontend-read aliases and engine_data so garage/current-vehicle cards
render identically across sources.
"""
import uuid

from django.test import TestCase
from django.urls import reverse

from apps.vehicles.models import AIVehicleEntry, Vehicle, VehicleIdentity


def _make_gvg(**kwargs):
    defaults = dict(
        make="Toyota", model="Camry", year=2018, variant="Altise",
        body_style="sedan", fcai_category="Medium",
        powertrain_type="petrol", fuel_type_raw="Petrol",
        fuel_consumption_combined_l_100km=7.8,
        tailpipe_co2_g_per_km=180.0, engine_l=2.5, drive="FWD",
        num_seats=5, transmission="Automatic", test_cycle="NEDC",
        driveaway_price_estimate=2800000,
    )
    defaults.update(kwargs)
    return VehicleIdentity.objects.create(**defaults)


def _make_ai(**kwargs):
    defaults = dict(
        search_query="toyota camry 2015", make="Toyota", model="Camry",
        year=2015, variant="Hybrid", body_style="sedan",
        powertrain_type="hybrid", fcai_category="Medium",
        fuel_consumption_combined_l_100km=5.3,
        tailpipe_co2_g_per_km=123.0, ancap_safety_rating=5, engine_l=2.5,
        drive="FWD", num_seats=5, driveaway_price_estimate=1650000,
    )
    defaults.update(kwargs)
    return AIVehicleEntry.objects.create(**defaults)


class VehicleDetailEndpointTests(TestCase):

    def test_carreb_id_keeps_serializer_response(self):
        v = Vehicle.objects.create(
            brand="Toyota", model="Corolla", year=2025, variant="Ascent Sport",
            powertrain_type="petrol", driveaway_price_by_state={"NSW": 3000000})
        resp = self.client.get(f"/api/vehicles/{v.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["brand"], "Toyota")
        self.assertEqual(resp.data["driveaway_price_by_state"], {"NSW": 3000000})

    def test_gvg_id_returns_catalogue_shaped_payload(self):
        rec = _make_gvg()
        resp = self.client.get(f"/api/vehicles/{rec.id}/")
        self.assertEqual(resp.status_code, 200)
        d = resp.data
        self.assertEqual(d["source"], "gvg")
        # Frontend-read aliases the Carreb serializer exposes.
        for key in ("brand", "make", "model", "year", "variant",
                    "tailpipe_co2_g_per_km", "annual_km_default", "seats",
                    "doors", "drive_type", "drivetrain", "drive",
                    "fuel_type", "fuel_consumption_l_100km",
                    "combined_fuel_consumption_l_100km",
                    "battery_capacity_kwh", "ancap_rating",
                    "ancap_safety_rating", "image_url", "body_style",
                    "transmission", "engine_l", "tow_braked_kg",
                    "tow_unbraked_kg", "test_cycle", "fcai_category",
                    "fcai_broad", "driveaway_price", "driveaway_price_by_state",
                    "name", "field_sources"):
            self.assertIn(key, d, f"missing alias {key}")
        self.assertEqual(d["brand"], "Toyota")
        self.assertEqual(d["seats"], 5)
        self.assertEqual(d["drive_type"], "FWD")
        # GVG rows carry no resale column — derived from the driveaway price.
        self.assertIsNotNone(d["resale_value_5yr_estimate"])
        self.assertEqual(d["resale_value_5yr"], d["resale_value_5yr_estimate"])
        self.assertGreater(d["resale_percent"], 0)
        # Engine/cost block, catalogue-shaped.
        ed = d["engine_data"]
        for key in ("total_annual_cost", "annual_cost_breakdown",
                    "tailpipe_co2_g_per_km", "annual_co2_kg", "annual_km",
                    "resale_value_5yr_estimate"):
            self.assertIn(key, ed, f"engine_data missing {key}")

    def test_ai_id_returns_catalogue_shaped_payload(self):
        entry = _make_ai()
        resp = self.client.get(f"/api/vehicles/{entry.id}/")
        self.assertEqual(resp.status_code, 200)
        d = resp.data
        self.assertEqual(d["source"], "ai")
        self.assertEqual(d["brand"], "Toyota")
        self.assertEqual(d["ancap_rating"], 5)
        self.assertIsNotNone(d["resale_value_5yr_estimate"])
        self.assertIn("engine_data", d)
        self.assertIn("total_annual_cost", d["engine_data"])

    def test_unknown_id_returns_404(self):
        resp = self.client.get(f"/api/vehicles/{uuid.uuid4()}/")
        self.assertEqual(resp.status_code, 404)
