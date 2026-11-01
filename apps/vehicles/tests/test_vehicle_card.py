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
        rec = _make_gvg(make="Mazda", model="3")
        # The card path is cache-READ-ONLY: a cold cache yields nothing and
        # must never call Grok inline.
        card = build_vehicle_card(rec, 'gvg')
        self.assertIsNone(card['ancap_safety_rating'])
        self.assertEqual(grok.call_count, 0)
        # Once a warmer populates the cache, the card picks the values up.
        from apps.vehicles.services.vehicle_card import warm_estimates
        warm_estimates("Mazda", "3", "Ascent", 2015, "petrol",
                       need_spec=False, need_ancap=True, need_engine=True)
        card = build_vehicle_card(rec, 'gvg')
        self.assertEqual(card['ancap_safety_rating'], 4)
        self.assertEqual(card['field_sources']['ancap_safety_rating'], 'ai')
        self.assertEqual(card['engine_l'], 1.8)

    def test_card_never_calls_grok_on_cold_cache(self):
        """Request-path guarantee: building any card with cold caches makes
        zero AI calls (responses must stay instant; warmers run off-request)."""
        from apps.mygarage.ai_service import _call_grok_json
        real = _call_grok_json
        calls = []
        def spy(*a, **k):
            calls.append(1)
            return real(*a, **k)
        with mock.patch("apps.mygarage.ai_service._call_grok_json", spy):
            build_vehicle_card(_make_gvg(make="Spy", model="Cold1"), 'gvg')
            build_vehicle_card(
                _make_ai(make="Spy", model="Cold2",
                         search_query="spy cold2 zz"), 'ai')
        self.assertEqual(calls, [])

    @mock.patch("apps.mygarage.ai_service._call_grok_json")
    def test_ai_record_missing_specs_backfilled_by_spec_sheet(self, grok):
        """Old cached AI rows (pre-spec-columns) heal via the combined
        spec-sheet estimator — one Grok call per car, cached 30 days —
        applied off-request, then served by the card."""
        grok.return_value = {
            "transmission": "automatic", "doors": 4, "fuel_tank_l": 60.0,
            "tow_braked_kg": 1200, "tow_unbraked_kg": 600,
            "test_cycle": "NEDC", "variant": "Altise",
            "confidence": "medium", "reasoning": "base sedan",
        }
        rec = _make_ai(variant="", powertrain_type="petrol",
                       search_query="toyota camry 2015 petrol specsheet")
        from apps.vehicles.services.vehicle_card import warm_estimates
        warm_estimates("Toyota", "Camry", "", 2015, "petrol",
                       need_spec=True, need_ancap=False, need_engine=False)
        self.assertEqual(grok.call_count, 1)  # one combined call, not six
        card = build_vehicle_card(rec, 'ai')
        self.assertEqual(card['transmission'], 'automatic')
        self.assertEqual(card['field_sources']['transmission'], 'ai')
        self.assertEqual(card['doors'], 4)
        self.assertEqual(card['fuel_tank_l'], 60.0)
        self.assertEqual(card['tow_braked_kg'], 1200)
        self.assertEqual(card['tow_unbraked_kg'], 600)
        self.assertEqual(card['test_cycle'], 'NEDC')
        self.assertEqual(card['variant'], 'Altise')
        self.assertEqual(card['field_sources']['variant'], 'ai')

    def test_combustion_car_electric_fields_are_zero_not_null(self):
        """A petrol car factually has no battery: 0.0, not null, and not
        badged as an estimate (structural truth)."""
        card = build_vehicle_card(
            _make_ai(powertrain_type="petrol", search_query="camry petrol zz"),
            'ai')
        for field in ('battery_kwh', 'electricity_consumption_wh_per_km',
                      'electric_range_km', 'wltp_range_km', 'range_battery_km'):
            self.assertEqual(card[field], 0.0, field)
            self.assertNotIn(field, card['field_sources'])

    def test_range_petrol_computed_from_tank_and_consumption(self):
        card = build_vehicle_card(
            _make_ai(powertrain_type="petrol", fuel_tank_l=60.0,
                     fuel_consumption_combined_l_100km=7.5,
                     search_query="camry range calc zz"),
            'ai')
        self.assertEqual(card['range_petrol_km'], 800)
        self.assertEqual(card['range_total_km'], 800)
        self.assertEqual(card['field_sources']['range_petrol_km'], 'default')

    def test_fcai_broad_from_registry(self):
        from apps.vehicles.models import FCAICategoryRegistry
        FCAICategoryRegistry.objects.create(
            segment_id=7, fcai_segment="Medium (under $60,000)",
            carreb_db_label="Medium", vehicle_class="Passenger")
        card = build_vehicle_card(
            _make_ai(fcai_broad="", search_query="camry broad zz"), 'ai')
        self.assertEqual(card['fcai_broad'], 'Passenger Cars')
        self.assertEqual(card['field_sources']['fcai_broad'], 'default')


class GvgCurrentVehicleEngineDataTests(TestCase):
    """GVG/AI current vehicles must expose the same engine_data keys the
    frontend renders for catalogue vehicles (running costs, CO2 p.a.,
    km p.a.) — previously only resale came through."""

    def _dial_rows(self, category="Medium", state="NSW"):
        from apps.vehicles.models import CoreDialBatch, CoreDialRow
        import uuid
        batch = CoreDialBatch.objects.create(
            scoring_version="t", as_at="2026-10-31", is_current=True)
        for vid, fuel, elec, ctp, ins, reg, srv, tyres in (
                (1, 300000, 0, 50000, 150000, 40000, 40000, 20000),
                (2, 340000, 0, 50000, 160000, 40000, 42000, 20000)):
            CoreDialRow.objects.create(
                batch=batch, state=state, fcai_category=category,
                version_id=vid, model_id="abc123", make="Toyota",
                model="Camry", variant="v", year=2015,
                fuel_cents=fuel, electricity_cents=elec,
                ctp_cents=ctp, comprehensive_cents=ins, registration_cents=reg,
                servicing_cents=srv, tyres_cents=tyres, road_user_charge_cents=0,
                driveaway_cents=2000000, coo_pa_cents=800000,
                annual_co2_kg=3000.0, price_score=0.5, emissions_score=0.5)
        return batch

    def test_engine_data_matches_catalogue_shape(self):
        from apps.vehicles.services.core_dial import cost_gvg_current_vehicle
        self._dial_rows()
        entry = _make_ai(powertrain_type="petrol",
                         search_query="engine data shape test")
        ed = cost_gvg_current_vehicle(entry, "NSW")
        for key in ('total_annual_cost', 'annual_cost_breakdown',
                    'tailpipe_co2_g_per_km', 'annual_co2_kg', 'annual_km',
                    'core_rating', 'is_estimate'):
            self.assertIn(key, ed, key)
        bd = ed['annual_cost_breakdown']
        for key in ('fuel_or_energy_annual', 'insurance_annual', 'ctp_annual',
                    'registration_annual', 'servicing_annual', 'tyres_annual',
                    'ev_levy_annual', 'total_annual'):
            self.assertIn(key, bd, key)
        # CO2 p.a. = g/km * km / 1000, consistent with the reported figures
        self.assertEqual(ed['annual_co2_kg'],
                         round(ed['tailpipe_co2_g_per_km'] * ed['annual_km'] / 1000))
        self.assertEqual(ed['tailpipe_co2_g_per_km'], 123.0)

    def test_card_annual_km_from_category_benchmark(self):
        from apps.vehicles.models import CategoryAnnualKMBenchmark
        CategoryAnnualKMBenchmark.objects.create(
            fcai_category="Medium", est_annual_km=15000)
        card = build_vehicle_card(
            _make_ai(search_query="annual km card test"), 'ai')
        self.assertEqual(card['annual_km'], 15000)
        self.assertEqual(card['field_sources']['annual_km'], 'default')

    @mock.patch("apps.mygarage.ai_service._call_grok_json")
    def test_carreb_missing_spec_ai_estimated(self, grok):
        """Catalogue rows with blank spec columns (all 1829 lack ANCAP/tow)
        pick up AI estimates from the warm caches, badged 'ai' — the card
        path itself stays cache-read-only."""
        grok.return_value = {
            "transmission": "automatic", "drive": "4WD", "doors": 4,
            "fuel_tank_l": 80.0, "tow_braked_kg": 3500,
            "tow_unbraked_kg": 750, "test_cycle": "WLTP",
            "variant": "XLT",
            "ancap_rating": 5, "engine_l": 2.4,
            "confidence": "high", "reasoning": "popular ute",
        }
        rec = _make_catalogue(brand="Ford", model="Ranger", year=2026,
                              variant="XLT", transmission="",
                              ancap_safety_rating=None, engine_l=None)
        from apps.vehicles.services.vehicle_card import (
            record_needs_warm, warm_estimates)
        _, needs = record_needs_warm(rec, 'carreb')
        self.assertTrue(needs)
        # Cold cache: card serves nulls and never calls Grok inline.
        card = build_vehicle_card(rec, 'carreb')
        self.assertIsNone(card['ancap_safety_rating'])
        self.assertEqual(grok.call_count, 0)
        # Warmer fills the caches; the card picks the values up.
        warm_estimates("Ford", "Ranger", "XLT", 2026, "diesel",
                       need_spec=True, need_ancap=True, need_engine=True)
        card = build_vehicle_card(rec, 'carreb')
        self.assertEqual(card['ancap_safety_rating'], 5)
        self.assertEqual(card['field_sources']['ancap_safety_rating'], 'ai')
        self.assertEqual(card['engine_l'], 2.4)
        self.assertEqual(card['field_sources']['engine_l'], 'ai')
        self.assertEqual(card['tow_braked_kg'], 3500)
        _, needs = record_needs_warm(rec, 'carreb')
        self.assertFalse(needs)

    @mock.patch("apps.mygarage.ai_service._call_grok_json")
    def test_spec_sheet_covers_drive(self, grok):
        """The combined spec-sheet estimator also fills an empty drive."""
        grok.return_value = {
            "transmission": "automatic", "drive": "awd",
            "doors": 4, "fuel_tank_l": 66.0,
            "tow_braked_kg": 3500, "tow_unbraked_kg": 750,
            "test_cycle": "WLTP", "variant": "LS-U",
            "confidence": "high", "reasoning": "popular ute",
        }
        from apps.vehicles.services.vehicle_card import warm_estimates
        warm_estimates("Isuzu", "D-Max", "LS-U", 2025, "diesel",
                       need_spec=True, need_ancap=False, need_engine=False)
        self.assertEqual(grok.call_count, 1)
        rec = _make_catalogue(brand="Isuzu", model="D-Max", year=2025,
                              variant="LS-U", drive="")
        card = build_vehicle_card(rec, 'carreb')
        self.assertEqual(card['drive'], 'AWD')
        self.assertEqual(card['field_sources']['drive'], 'ai')
        self.assertEqual(card['tow_braked_kg'], 3500)
