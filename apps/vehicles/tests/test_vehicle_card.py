"""Tests for the canonical full-field vehicle card."""
from unittest import mock

from django.test import TestCase

from apps.vehicles.models import (
    AIVehicleEntry,
    CategoryCostDefault,
    Vehicle,
    VehicleIdentity,
)
from apps.vehicles.services.vehicle_card import (
    CARD_FIELDS,
    build_vehicle_card,
    nearest_catalogue_price,
)


def _make_catalogue(**kwargs):
    defaults = dict(
        brand="Toyota", model="Hilux", year=2026, variant="SR5 Double Cab",
        body_style="ute", powertrain_type="diesel", fcai_category="Ute",
        drive="4x4", engine_l=2.8, num_seats=5, ancap_safety_rating=5,
        fuel_consumption_per_100km=7.9, tailpipe_co2_g_per_km=208.0,
        image_url="/media/vehicle_images/toyota-hilux-2026.png",
        driveaway_price_by_state={"NSW": 6716200, "VIC": 6667700},
        servicing_5yr_estimate=250000, tyre_replacement_estimate=160000,
        resale_value_5yr_estimate=3800000,
        ctp_by_state={"NSW": 50000}, insurance_estimate_by_state={"NSW": 150000},
        registration_by_state={"NSW": 40000},
        total_5yr_cost_of_ownership_by_state={"NSW": 21000000},
    )
    defaults.update(kwargs)
    return Vehicle.objects.create(**defaults)


def _make_gvg(**kwargs):
    defaults = dict(
        make="Toyota", model="Corolla", year=2015, variant="Ascent",
        body_style="hatchback", fcai_category="Small",
        powertrain_type="petrol",
        fuel_consumption_combined_l_100km=6.1, tailpipe_co2_g_per_km=143.0,
    )
    defaults.update(kwargs)
    return VehicleIdentity.objects.create(**defaults)


def _make_ai(**kwargs):
    defaults = dict(
        search_query="toyota camry 2015", make="Toyota", model="Camry",
        year=2015, variant="Hybrid", body_style="sedan",
        powertrain_type="hybrid", fcai_category="Medium",
        fuel_consumption_combined_l_100km=5.3, tailpipe_co2_g_per_km=123.0,
        ancap_safety_rating=5, engine_l=2.5, drive="FWD", num_seats=5,
        driveaway_price_estimate=1650000,
    )
    defaults.update(kwargs)
    return AIVehicleEntry.objects.create(**defaults)


class VehicleCardTests(TestCase):

    def test_card_contains_every_schema_field_for_all_sources(self):
        rows = [
            (_make_catalogue(), 'carreb'),
            (_make_gvg(), 'gvg'),
            (_make_ai(), 'ai'),
        ]
        for record, source in rows:
            card = build_vehicle_card(record, source)
            for field in CARD_FIELDS:
                self.assertIn(field, card, f"{source} missing {field}")
            self.assertEqual(card['source'], source)
            self.assertEqual(card['id'], str(record.id))
            self.assertIsInstance(card['field_sources'], dict)

    def test_carreb_values_are_db_provenance(self):
        card = build_vehicle_card(_make_catalogue(), 'carreb')
        self.assertEqual(card['driveaway_price'], 6716200)  # NSW default state
        self.assertEqual(card['field_sources']['driveaway_price'], 'db')
        self.assertEqual(card['field_sources']['engine_l'], 'db')
        self.assertEqual(card['driveaway_price_display'], "$67,162")

    def test_gvg_missing_costs_filled_from_sheet_defaults(self):
        CategoryCostDefault.objects.create(
            fcai_category="Small", state="NSW",
            ctp_pa=45000, comprehensive_pa=120000, registration_pa=35000,
            maintenance_pa=25000, tyre_cost_pa=15000, fuel_cost_pa=150000,
            servicing_5yr_estimate=120000, tyre_replacement_estimate=80000)
        card = build_vehicle_card(_make_gvg(), 'gvg', state='NSW')
        self.assertEqual(card['ctp_by_state'], {"NSW": 45000})
        self.assertEqual(card['field_sources']['ctp_by_state'], 'default')
        self.assertEqual(card['servicing_5yr_estimate'], 120000)
        self.assertEqual(card['field_sources']['servicing_5yr_estimate'], 'default')
        # Consumption came straight from the GVG row.
        self.assertEqual(card['fuel_consumption_combined_l_100km'], 6.1)
        self.assertEqual(
            card['field_sources']['fuel_consumption_combined_l_100km'], 'db')

    def test_ai_values_are_ai_provenance(self):
        card = build_vehicle_card(_make_ai(), 'ai')
        self.assertEqual(card['ancap_safety_rating'], 5)
        self.assertEqual(card['field_sources']['ancap_safety_rating'], 'ai')
        self.assertEqual(card['driveaway_price'], 1650000)

    def test_missing_ai_price_uses_nearest_catalogue_year(self):
        # Catalogue only has MY2026; a 2025 AI Hilux gets that price as a
        # sheet/defaults-tier estimate — the user's exact Hilux scenario.
        twin = _make_catalogue()
        card = build_vehicle_card(
            _make_ai(make="Toyota", model="Hilux", year=2025,
                     driveaway_price_estimate=None),
            'ai')
        self.assertEqual(card['driveaway_price'], twin.driveaway_price_by_state['NSW'])
        self.assertEqual(card['field_sources']['driveaway_price'], 'default')

    def test_nearest_catalogue_price_picks_closest_year(self):
        _make_catalogue(year=2022, driveaway_price_by_state={"NSW": 6100000})
        twin = _make_catalogue(year=2026, driveaway_price_by_state={"NSW": 6716200})
        self.assertEqual(
            nearest_catalogue_price("Toyota", "Hilux", 2025), 6716200)
        self.assertEqual(
            nearest_catalogue_price("Toyota", "Hilux", 2025, exclude_id=twin.id),
            6100000)

    @mock.patch("apps.mygarage.ai_service._call_grok_json")
    def test_gvg_missing_spec_ai_estimated(self, grok):
        grok.return_value = {"ancap_rating": 4, "engine_l": 1.8}
        # Unique name so the 30-day estimate cache can't carry a miss over
        # from the earlier GVG tests in this module.
        card = build_vehicle_card(_make_gvg(make="Mazda", model="3"), 'gvg')
        self.assertEqual(card['ancap_safety_rating'], 4)
        self.assertEqual(card['field_sources']['ancap_safety_rating'], 'ai')
        self.assertEqual(card['engine_l'], 1.8)
