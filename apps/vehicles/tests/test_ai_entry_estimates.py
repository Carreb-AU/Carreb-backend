"""Tests for filling AIVehicleEntry cost fields from sheet defaults."""
from django.test import TestCase

from apps.vehicles.models import (
    AIVehicleEntry,
    CategoryAnnualKMBenchmark,
    CategoryCostDefault,
    StateEnergyPrice,
)
from apps.vehicles.services.ai_entry_estimates import fill_ai_entry_estimates


def _seed_defaults():
    CategoryCostDefault.objects.create(
        fcai_category="Medium", state="NSW", annual_km=13300,
        ctp_pa=50000, comprehensive_pa=150000, registration_pa=40000,
        maintenance_pa=30000, tyre_cost_pa=20000,
        fuel_cost_pa=180000, electricity_cost_pa=0, ev_levy_pa=0,
        servicing_5yr_estimate=150000, tyre_replacement_estimate=100000)
    CategoryCostDefault.objects.create(
        fcai_category="Medium", state="VIC", annual_km=13300,
        ctp_pa=45000, comprehensive_pa=140000, registration_pa=35000,
        maintenance_pa=30000, tyre_cost_pa=20000,
        fuel_cost_pa=180000, electricity_cost_pa=0, ev_levy_pa=0,
        servicing_5yr_estimate=150000, tyre_replacement_estimate=100000)
    StateEnergyPrice.objects.create(
        state="NSW", petrol_ulp95_cents_per_litre=240,
        diesel_cents_per_litre=280, electricity_cents_per_kwh=30.0)
    StateEnergyPrice.objects.create(
        state="VIC", petrol_ulp95_cents_per_litre=235,
        diesel_cents_per_litre=275, electricity_cents_per_kwh=28.0)
    CategoryAnnualKMBenchmark.objects.create(
        fcai_category="Medium", est_annual_km=13000)


def _make_entry(**kwargs):
    defaults = dict(
        search_query="toyota camry 2015", make="Toyota", model="Camry",
        year=2015, variant="Hybrid", body_style="sedan",
        powertrain_type="hybrid", fcai_category="Medium",
        fuel_consumption_combined_l_100km=5.3)
    defaults.update(kwargs)
    return AIVehicleEntry.objects.create(**defaults)


class FillAIEntryEstimatesTests(TestCase):

    def setUp(self):
        _seed_defaults()

    def test_fills_all_cost_fields(self):
        entry = fill_ai_entry_estimates(_make_entry())
        self.assertEqual(entry.ctp_by_state["NSW"], 50000)
        self.assertEqual(entry.insurance_estimate_by_state["VIC"], 140000)
        self.assertEqual(entry.registration_by_state["NSW"], 40000)
        self.assertEqual(entry.servicing_5yr_estimate, 150000)
        self.assertEqual(entry.tyre_replacement_estimate, 100000)
        self.assertEqual(len(entry.total_5yr_cost_of_ownership_by_state), 2)

    def test_5yr_total_uses_own_consumption(self):
        # 5.3 L/100km * 13000 km * $2.40/L = $1,653.60/yr fuel in NSW.
        entry = fill_ai_entry_estimates(_make_entry())
        expected_annual = (50000 + 150000 + 40000 + 30000 + 20000
                           + round(5.3 / 100 * 13000 * 240))
        self.assertEqual(entry.total_5yr_cost_of_ownership_by_state["NSW"],
                         expected_annual * 5)

    def test_idempotent_and_preserves_existing(self):
        entry = _make_entry(servicing_5yr_estimate=999999)
        fill_ai_entry_estimates(entry)
        entry.refresh_from_db()
        self.assertEqual(entry.servicing_5yr_estimate, 999999)
        self.assertIsNotNone(entry.ctp_by_state)
        fill_ai_entry_estimates(entry)  # second run is a no-op
        entry.refresh_from_db()
        self.assertEqual(entry.ctp_by_state["NSW"], 50000)

    def test_missing_category_leaves_fields_empty(self):
        entry = fill_ai_entry_estimates(_make_entry(fcai_category="Nope"))
        self.assertIsNone(entry.ctp_by_state)
        self.assertIsNone(entry.total_5yr_cost_of_ownership_by_state)
