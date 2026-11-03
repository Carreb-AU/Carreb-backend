"""Held (suppressed) listings must never surface in search, matches, bands
or counts (Bug Register 3-Nov-26, B-12)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.freematch.models import FreeMatchSession
from apps.freematch.selectors import (
    get_freematch_candidates,
    get_freematch_candidates_base,
    get_freematch_candidates_relaxed,
    get_freematch_candidates_fuel_only,
)
from apps.vehicles.models import PowertrainType, Vehicle
from apps.vehicles.services.vehicle_card import nearest_catalogue_price

User = get_user_model()


def _vehicle(brand="TestMake", model="TestModel", suppressed=False, **kwargs):
    defaults = dict(
        brand=brand, model=model, year=2026, variant="Base",
        body_style="suv", fcai_category="Medium SUV",
        powertrain_type=PowertrainType.PETROL, num_seats=5,
        driveaway_price_by_state={"NSW": 50_000_00},
    )
    defaults.update(kwargs)
    return Vehicle.objects.create(is_suppressed=suppressed, **defaults)


class VehicleListSuppressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        _vehicle(brand="OpenMake")
        _vehicle(brand="HeldMake", suppressed=True)

    def test_list_excludes_suppressed(self):
        resp = self.client.get(reverse("vehicle-list"))
        self.assertEqual(resp.status_code, 200)
        brands = {v["brand"] for v in resp.data["results"]}
        self.assertEqual(brands, {"OpenMake"})

    def test_dropdowns_exclude_suppressed(self):
        self.assertEqual(self.client.get(reverse("vehicle-brands")).json(), ["OpenMake"])
        _vehicle(brand="OpenMake", model="HeldModel", suppressed=True)
        self.assertEqual(
            self.client.get(reverse("vehicle-models"), {"brand": "OpenMake"}).json(),
            ["TestModel"],
        )


class FreeMatchSuppressionTests(TestCase):
    def setUp(self):
        self.session = FreeMatchSession.objects.create(state="NSW")
        _vehicle(brand="OpenMake")
        _vehicle(brand="HeldMake", suppressed=True)

    def test_candidates_exclude_suppressed(self):
        qs = get_freematch_candidates(self.session)
        self.assertEqual(qs.count(), 1)

    def test_all_selector_variants_exclude_suppressed(self):
        for qs in (
            get_freematch_candidates_base(),
            get_freematch_candidates_relaxed(self.session),
            get_freematch_candidates_fuel_only(None),
        ):
            self.assertNotIn("HeldMake", list(qs.values_list("brand", flat=True)))


class NearestTwinSuppressionTests(TestCase):
    def test_nearest_catalogue_price_ignores_suppressed_twins(self):
        _vehicle(brand="TwinMake", model="TwinModel", year=2024,
                 driveaway_price_by_state={"NSW": 40_000_00})
        _vehicle(brand="TwinMake", model="TwinModel", year=2025,
                 driveaway_price_by_state={"NSW": 60_000_00}, suppressed=True)
        self.assertEqual(
            nearest_catalogue_price("TwinMake", "TwinModel", 2025), 40_000_00)
