"""Sheet-default cost estimates for uncosted catalogue vehicles.

Pins the fill pipeline in apps/vehicles/services/uncosted_estimates.py to the
workbook Formulas tab: component sums, mode COO wiring (B/E/C/F), energy-cycle
CO2, scoring bounds, stars/band, and provenance markers.
"""
from django.test import TestCase

from apps.vehicles.models import (
    CategoryAnnualKMBenchmark,
    CategoryScoringBounds,
    CTPStateDefault,
    DepreciationBrandModifier,
    DepreciationLookup,
    EnergyTypeCostModifier,
    FinanceDefault,
    InsuranceCategoryBenchmark,
    InsuranceStateModifier,
    MaintenanceCategoryDefault,
    NGAEmissionFactor,
    RegistrationFeeByState,
    StateEnergyPrice,
    TyreCategoryDefault,
    Vehicle,
)
from apps.vehicles.services.rating_engine import _get_stored_mode_data
from apps.vehicles.services.uncosted_estimates import (
    _Lookups,
    apply_estimates,
    compute_vehicle_estimates,
    find_uncosted_vehicles,
)


def _seed_platform_defaults():
    for state in ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"):
        StateEnergyPrice.objects.create(
            state=state, data_period="test", source="test",
            petrol_ulp95_cents_per_litre=240,
            diesel_cents_per_litre=280,
            electricity_cents_per_kwh=34.0,
        )
        CTPStateDefault.objects.create(state=state, annual_ctp_cents=50_000, source="test")
        RegistrationFeeByState.objects.create(fcai_category="Sports", state=state, annual_fee_cents=47_500)
    for cat, km in (("Sports", 9000), ("Medium", 13000)):
        CategoryAnnualKMBenchmark.objects.create(fcai_category=cat, est_annual_km=km)
        InsuranceCategoryBenchmark.objects.create(fcai_category=cat, national_avg_cents_pa=194_100, estimated_monthly_cents=16_175)
        MaintenanceCategoryDefault.objects.create(fcai_category=cat, five_year_total_cents=1_675_00, annual_avg_cents=33_500, year1_cents=20_000, year5_cents=50_000, representative_vehicle='Test', service_interval='12mo')
        TyreCategoryDefault.objects.create(
            fcai_category=cat, replacement_interval_km=40_000,
            cost_per_set_4_cents=68_800, annualised_cost_cents=13_760,
            typical_tyre_size="test", source="test")
    for state, mod in (("NSW", 1.135), ("VIC", 1.339), ("QLD", 0.882)):
        InsuranceStateModifier.objects.create(state=state, state_modifier=mod, avg_comprehensive_cents=200_000, national_avg_cents=170_000)
    EnergyTypeCostModifier.objects.create(cost_component="Maintenance", ice_petrol_multiplier=1.0, ice_diesel_multiplier=1.0, hev_hybrid_multiplier=1.0, bev_multiplier=0.75, phev_multiplier=1.07)
    EnergyTypeCostModifier.objects.create(cost_component="Comprehensive Insurance", ice_petrol_multiplier=1.0, ice_diesel_multiplier=1.0, hev_hybrid_multiplier=1.0, bev_multiplier=1.3, phev_multiplier=1.0)
    FinanceDefault.objects.create(
        fcai_category_broad="Passenger Cars",
        deposit_pct=10.0, base_rate_pct=8.85, alt_fuel_modifier_pct=-0.5,
        term_months=60, balloon_pct=0.0,
        estab_fee_default=25_000, estab_fee_bev=25_000, admin_fee_monthly=700,
    )
    DepreciationLookup.objects.create(layer_num=1, key="Sports", modifier=0.35)
    DepreciationLookup.objects.create(layer_num=2, key="petrol", powertrain_type="petrol", modifier=1.0)
    DepreciationBrandModifier.objects.create(brand="Ferrari", retention_multiplier=1.0)
    NGAEmissionFactor.objects.create(grid="NSW/ACT", states_covered="NSW, ACT",
                                     scope2_factor_kgco2e_per_kwh=0.6, edition="test")
    CategoryScoringBounds.objects.create(
        fcai_category="Sports", core_mode="B", scoring_version="v6.4-audit-29Oct26",
        cat_min_coo=4_000.0, cat_max_coo=8_000.0, cat_min_co2=120.0, cat_max_co2=450.0,
    )


def _sports_car(**kwargs):
    defaults = dict(
        brand="Ferrari", model="Testarossa", year=2026, variant="Base",
        body_style="coupe", fcai_category="Sports", fcai_broad="Passenger Cars",
        powertrain_type="petrol", num_seats=2, base_fuel="petrol",
        driveaway_price_by_state={"NSW": 32_500_000},  # $325,000
        fuel_consumption_per_100km=10.5,
        tailpipe_co2_g_per_km=245.0,
        mode_data_by_state={"NSW": {"B": {}, "E": {}, "C": {}, "F": {}}},
    )
    defaults.update(kwargs)
    return Vehicle.objects.create(**defaults)


class UncostedEstimateTests(TestCase):
    def setUp(self):
        _seed_platform_defaults()
        self.lookups = _Lookups()

    def test_component_sum_matches_workbook_formula(self):
        car = _sports_car()
        result = compute_vehicle_estimates(car, self.lookups)
        st = result["states"]["NSW"]
        comps = st["components"]
        # fuel: 10.5 L/100km x 90 (9000 km/100) x $2.40
        self.assertEqual(comps["fuel_cost_pa"], 2268.0)
        self.assertEqual(comps["ctp_pa"], 500.0)
        # comprehensive: $1,941 x NSW 1.135
        self.assertEqual(comps["comprehensive_pa"], 2203.04)
        self.assertEqual(comps["registration_pa"], 475.0)
        self.assertEqual(comps["maintenance_pa"], 335.0)
        # tyres: floor(9000x5/40000)=1 set x $688 / 5
        self.assertEqual(comps["tyre_cost_pa"], 137.6)
        self.assertEqual(st["base_coo_pa"], 5918.64)

    def test_mode_coo_wiring(self):
        car = _sports_car()
        result = compute_vehicle_estimates(car, self.lookups)
        st = result["states"]["NSW"]
        modes = st["mode_coo_pa"]
        self.assertEqual(modes["B"], st["base_coo_pa"])
        # C = base + value lost; resale = 325000 x 0.35 = 113,750
        self.assertEqual(st["resale_5yr"], 113_750.0)
        self.assertEqual(modes["C"], round(st["base_coo_pa"] + (325_000 - 113_750) / 5, 2))
        # E adds finance; F adds both
        self.assertGreater(modes["E"], modes["B"])
        self.assertGreater(modes["F"], modes["E"])
        self.assertGreater(modes["F"], modes["C"])

    def test_energy_cycle_co2(self):
        car = _sports_car()
        result = compute_vehicle_estimates(car, self.lookups)
        st = result["states"]["NSW"]
        # 10.5 x 10 x 2.9 (petrol scope 1+3), no grid leg
        self.assertEqual(st["co2"]["co2_energy_cycle_g_km"], 304.5)
        self.assertEqual(st["co2"]["annual_co2_kg"], 2741)

    def test_scores_stars_band_via_bounds(self):
        car = _sports_car()
        result = compute_vehicle_estimates(car, self.lookups)
        # price: 1 - (5918.64-4000)/4000 = 0.52034
        self.assertAlmostEqual(result["national"]["B"]["price_score"], 0.52034, places=5)
        # CO2 cap at national energy-cycle 304.5 -> tier 3.4 (>=250)
        self.assertEqual(result["co2_cap_tier"], 3.4)
        self.assertGreaterEqual(result["national"]["B"]["stars"], 1)
        self.assertTrue(result["national"]["B"]["band_name"].endswith("™"))

    def test_apply_marks_provenance_and_stored_read(self):
        car = _sports_car()
        result = compute_vehicle_estimates(car, self.lookups)
        apply_estimates(car, result, commit=True)
        car.refresh_from_db()
        self.assertEqual(car.annual_km_default, 9000)
        self.assertIn("uncosted-cost-fill", car.assumption_fills)
        stored = _get_stored_mode_data(car, "NSW", "pure_cost")
        self.assertIsNotNone(stored)
        self.assertAlmostEqual(stored["mode_coo_pa"], 5918.64, places=2)
        md = car.mode_data_by_state["NSW"]["B"]
        self.assertEqual(md["costing_basis"], "sheet_defaults_v6.4")

    def test_find_uncosted_excludes_after_fill(self):
        car = _sports_car()
        self.assertIn(car.pk, list(find_uncosted_vehicles().values_list("pk", flat=True)))
        result = compute_vehicle_estimates(car, self.lookups)
        apply_estimates(car, result, commit=True)
        self.assertNotIn(car.pk, list(find_uncosted_vehicles().values_list("pk", flat=True)))

    def test_sibling_price_fallback(self):
        priced = _sports_car(model="Roma", variant="Priced")
        unpriced = _sports_car(
            model="Roma", variant="Unpriced",
            driveaway_price_by_state={"NSW": None, "VIC": None},
        )
        result = compute_vehicle_estimates(unpriced, self.lookups)
        self.assertIsNotNone(result)
        self.assertTrue(result["price_estimated"])
        self.assertEqual(result["states"]["NSW"]["driveaway"], 325_000.0)

    def test_no_price_source_returns_none(self):
        car = _sports_car(driveaway_price_by_state={"NSW": None})
        # No sibling for this model.
        self.assertIsNone(compute_vehicle_estimates(car, self.lookups))
