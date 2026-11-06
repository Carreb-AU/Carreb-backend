"""B-21 garage-level km normalisation tests.

Every card in MyGarage (current vehicle included) is costed at the user's
garage km: their Edit Vehicle km setting, else the ABS 2020 default of
12,100 km/yr. km p.a. is a direct user input only — the odometer ÷
years-since-purchase derivation was retired 6-Nov-26 (Jock: it assumed the
car was bought new and overstated on used cars); odometer and purchase
date stay on the record, optional, feeding resale only. Only the
km-dependent cost lines (fuel/energy, servicing, tyres, EV road-user levy)
and annual CO2 scale; rego, CTP, insurance, finance and depreciation never
do. CORE ratings/stars stay on dataset km (D29/D30).
"""
import datetime
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.mygarage.models import (
    CurrentVehicle, GarageVehicle, GarageVehicleSource, UserPriorityState)
from apps.users.models import User
from apps.vehicles.models import (
    CategoryAnnualKMBenchmark, CoreDialBatch, CoreDialRow, Vehicle,
    VehicleIdentity)
from apps.vehicles.services.core_dial import (
    GARAGE_KM_DEFAULT, cost_gvg_current_vehicle,
    garage_km_copy_line, resolve_garage_km)
from apps.vehicles.services.rating_engine import (
    calculate_core_rating, calculate_vehicle_cost_breakdown)


def _ns(**kwargs):
    return SimpleNamespace(**kwargs)


def _catalogue(**kwargs):
    defaults = dict(
        brand="Toyota", model="Camry", year=2025, variant="SX",
        body_style="sedan", powertrain_type="petrol", fcai_category="Medium",
        annual_km_default=15000,
        fuel_cost_by_state={"NSW": 200000},           # $2,000/yr
        insurance_estimate_by_state={"NSW": 300000},  # $3,000/yr
        ctp_by_state={"NSW": 50000},
        registration_by_state={"NSW": 120000},
        servicing_5yr_estimate=1_000_000,             # 5yr $10,000 (cents)
        tyre_replacement_estimate=1_500_000,          # 5yr $15,000 (cents)
        mode_data_by_state={"NSW": {"B": {
            "mode_coo_pa": 5000.0, "annual_co2_kg": 2000.0, "stars": 4,
        }}},
    )
    defaults.update(kwargs)
    return Vehicle.objects.create(**defaults)


class ResolveGarageKmTests(TestCase):

    def test_default_when_nothing_set(self):
        self.assertEqual(resolve_garage_km(None),
                         (GARAGE_KM_DEFAULT, 'default'))

    def test_odometer_derivation_retired(self):
        # However plausible the odometer + purchase date pair, it no longer
        # produces a km rate (Jock, 6-Nov-26): km p.a. is a user input only.
        today = datetime.date.today()
        cv = _ns(odometer_reading=20000,
                 purchase_date=today - datetime.timedelta(days=730))
        self.assertEqual(resolve_garage_km(None), (GARAGE_KM_DEFAULT, 'default'))

    def test_user_setting_wins(self):
        ps = _ns(garage_km=22000, garage_km_user_set=True)
        self.assertEqual(resolve_garage_km(ps), (22000, 'user'))

    def test_copy_line_variants(self):
        self.assertEqual(
            garage_km_copy_line(12100, 'default'),
            "Costed at 12,100 km/yr (ABS 2020). Change in Edit Vehicle.")
        self.assertEqual(
            garage_km_copy_line(14000, 'user'),
            "Costed at 14,000 km/yr, your setting.")


class LaunchAmendmentTests(TestCase):
    """6-Nov register amendments: band name/slug, neutral direction,
    off-grid CO2 (B-29 blocker, B-34, off-grid EV proof)."""

    def test_band_name_and_slug_everyday_legend(self):
        from apps.vehicles.services.rating_engine import get_band_name, get_band_slug
        self.assertEqual(get_band_name(4.9), "Everyday Legend™")
        self.assertEqual(get_band_slug(4.9), "everyday-legend")
        self.assertEqual(get_band_name(5.0), "Everyday Legend™")
        self.assertEqual(get_band_slug(3.9), "smart-move")

    def test_est_cost_difference_same_when_it_rounds_to_zero(self):
        v = _catalogue()
        base = calculate_core_rating(v, 'NSW', 3, 'pure_cost', {},
                                     current_vehicle_annual_cost=0)
        total = base['total_annual_cost']

        # Card costs 30c more than the baseline -> rounds to $0/yr -> "same".
        res = calculate_core_rating(v, 'NSW', 3, 'pure_cost', {},
                                    current_vehicle_annual_cost=total - 30)
        diff = res['est_cost_difference']
        self.assertEqual(diff['direction'], 'same')
        self.assertEqual(diff['value_cents'], 0)
        self.assertEqual(diff['est_5yr_savings'], 0)

        # A real $500 difference still colours (baseline $500 cheaper than
        # the card -> the card is more expensive).
        res = calculate_core_rating(v, 'NSW', 3, 'pure_cost', {},
                                    current_vehicle_annual_cost=total - 50000)
        self.assertEqual(res['est_cost_difference']['direction'],
                         'more_expensive')
        self.assertEqual(res['est_cost_difference']['value_cents'], 50000)

    def test_off_grid_override_scales_bev_energy_cycle_co2(self):
        v = _catalogue(powertrain_type='bev', tailpipe_co2_g_per_km=0,
                       energy_consumption_wh_km=180,
                       fuel_cost_by_state={}, ev_levy_by_state={},
                       electricity_cost_by_state={"NSW": 100000},
                       co2_energy_cycle_g_per_km=130.7)
        # No override: dataset figure verbatim.
        res0 = calculate_core_rating(v, 'NSW', 3, 'pure_cost', {})
        self.assertEqual(res0['co2_energy_cycle_g_per_km'], 130.7)
        self.assertEqual(res0['annual_co2_kg'], 2000)

        # 50% off-grid replaces the dataset 0.20 share:
        # 130.7 x (1 - 0.50) / (1 - 0.20) = 81.7, and the kg line scales
        # by the same ratio (2000 x 81.7/130.7 = 1250).
        res50 = calculate_core_rating(v, 'NSW', 3, 'pure_cost',
                                      {'off_grid_energy_percent': 50})
        self.assertEqual(res50['co2_energy_cycle_g_per_km'], 81.7)
        self.assertEqual(res50['annual_co2_kg'], 1250)

        # Explicit 0 behaves like absent.
        res_same = calculate_core_rating(v, 'NSW', 3, 'pure_cost',
                                         {'off_grid_energy_percent': 0})
        self.assertEqual(res_same['co2_energy_cycle_g_per_km'], 130.7)
        self.assertEqual(res_same['annual_co2_kg'], 2000)


class BreakdownScalingTests(TestCase):

    def test_only_km_dependent_lines_scale(self):
        v = _catalogue()
        base = calculate_vehicle_cost_breakdown(
            v, 'NSW', 'pure_cost', {}, costed_km=None)
        scaled = calculate_vehicle_cost_breakdown(
            v, 'NSW', 'pure_cost', {}, costed_km=30000)  # factor 2

        # Scaled x2: fuel, servicing, tyres.
        self.assertEqual(scaled['fuel_or_energy_annual'],
                         base['fuel_or_energy_annual'] * 2)
        self.assertEqual(scaled['servicing_annual'],
                         base['servicing_annual'] * 2)
        self.assertEqual(scaled['tyres_annual'], base['tyres_annual'] * 2)
        # Fixed lines untouched.
        self.assertEqual(scaled['insurance_annual'],
                         base['insurance_annual'])
        self.assertEqual(scaled['ctp_annual'], base['ctp_annual'])
        self.assertEqual(scaled['registration_annual'],
                         base['registration_annual'])
        self.assertEqual(scaled['total_annual'],
                         base['total_annual']
                         + base['fuel_or_energy_annual']
                         + base['servicing_annual']
                         + base['tyres_annual'])

    def test_ev_levy_scales_as_per_km_charge(self):
        v = _catalogue(powertrain_type='bev',
                       fuel_cost_by_state={},
                       electricity_cost_by_state={"NSW": 100000},
                       ev_levy_by_state={"NSW": 50000})
        base = calculate_vehicle_cost_breakdown(
            v, 'NSW', 'pure_cost', {}, costed_km=None)
        scaled = calculate_vehicle_cost_breakdown(
            v, 'NSW', 'pure_cost', {}, costed_km=30000)
        self.assertEqual(scaled['ev_levy_annual'], base['ev_levy_annual'] * 2)
        self.assertEqual(scaled['fuel_or_energy_annual'],
                         base['fuel_or_energy_annual'] * 2)

    def test_costed_km_equal_to_category_km_is_a_noop(self):
        v = _catalogue()
        base = calculate_vehicle_cost_breakdown(
            v, 'NSW', 'pure_cost', {}, costed_km=None)
        same = calculate_vehicle_cost_breakdown(
            v, 'NSW', 'pure_cost', {}, costed_km=15000)
        self.assertEqual(base, same)

    def test_per_line_overrides_replace_dataset_lines(self):
        v = _catalogue()
        d = calculate_vehicle_cost_breakdown(v, 'NSW', 'pure_cost', {
            'insurance_override': 2500,      # $2,500/yr
            'registration_override': 800,    # $800/yr
            'servicing_override': 600,       # $600/yr
            'tyres_override': 400,           # $400/yr
        })
        self.assertEqual(d['insurance_annual'], 250000)
        self.assertEqual(d['registration_annual'], 80000)
        self.assertEqual(d['servicing_annual'], 60000)
        self.assertEqual(d['tyres_annual'], 40000)

    def test_override_is_not_km_scaled(self):
        # A user-entered line is their figure at their km — the servicing
        # override must NOT be doubled along with the dataset lines.
        v = _catalogue()
        d = calculate_vehicle_cost_breakdown(v, 'NSW', 'pure_cost', {
            'servicing_override': 600,
        }, costed_km=30000)
        self.assertEqual(d['servicing_annual'], 60000)
        self.assertEqual(d['fuel_or_energy_annual'], 400000)  # dataset x2

    def test_resale_override_replaces_workbook_credit(self):
        v = _catalogue(driveaway_price_by_state={"NSW": 50_000_00})
        d = calculate_vehicle_cost_breakdown(
            v, 'NSW', 'true_value', {'resale_value_override': 30000})
        # (50,000 - 30,000) / 5 = $4,000/yr credit = 400,000 cents.
        self.assertEqual(d['resale_credit_annual'], 400000)


class CoreRatingKmScalingTests(TestCase):

    def test_card_total_reconciles_stored_total_with_variable_lines(self):
        v = _catalogue()
        unscaled = calculate_core_rating(v, 'NSW', 3, 'pure_cost', {})
        # Stored workbook total is untouched without costed_km.
        self.assertEqual(unscaled['total_annual_cost'], 500000)

        # At double the km: stored total + variable lines x (factor - 1).
        # Variable lines at category km: fuel 200000 + servicing 200000
        # + tyres 300000 = 700000 cents.
        scaled = calculate_core_rating(
            v, 'NSW', 3, 'pure_cost', {}, costed_km=30000)
        self.assertEqual(scaled['total_annual_cost'], 500000 + 700000)
        # At exactly the category km the card equals the dataset figure.
        same_km = calculate_core_rating(
            v, 'NSW', 3, 'pure_cost', {}, costed_km=15000)
        self.assertEqual(same_km['total_annual_cost'], 500000)
        # And it is lower at fewer km.
        low_km = calculate_core_rating(
            v, 'NSW', 3, 'pure_cost', {}, costed_km=7500)
        self.assertEqual(low_km['total_annual_cost'], 500000 - 350000)

    def test_rating_and_stars_stay_on_dataset_values(self):
        v = _catalogue()
        unscaled = calculate_core_rating(v, 'NSW', 3, 'pure_cost', {})
        scaled = calculate_core_rating(
            v, 'NSW', 3, 'pure_cost', {}, costed_km=45000)
        self.assertEqual(scaled['core_rating'], unscaled['core_rating'])
        self.assertEqual(scaled['core_rating'], 4.0)
        self.assertEqual(scaled['band_slug'], unscaled['band_slug'])

    def test_annual_co2_scales_with_km(self):
        v = _catalogue()
        scaled = calculate_core_rating(
            v, 'NSW', 3, 'pure_cost', {}, costed_km=30000)
        self.assertEqual(scaled['annual_co2_kg'], 4000)  # 2000 kg x factor 2

    def test_cost_difference_uses_scaled_both_sides(self):
        v = _catalogue()
        res = calculate_core_rating(
            v, 'NSW', 3, 'pure_cost', {}, costed_km=30000,
            current_vehicle_annual_cost=2_000_000)
        diff = res['est_cost_difference']
        self.assertEqual(diff['comparison_mode'], 'current_vehicle')
        self.assertEqual(diff['direction'], 'saving')
        self.assertEqual(diff['value_cents'],
                         2_000_000 - res['total_annual_cost'])

    def test_fixed_band_fixed_line_override_moves_total_at_category_km(self):
        # Insurance $2,500 vs dataset $3,000: the stored Mode COO moves by
        # exactly the line delta even when km is at the dataset value.
        v = _catalogue()
        res = calculate_core_rating(
            v, 'NSW', 3, 'pure_cost', {'insurance_override': 2500})
        self.assertEqual(res['total_annual_cost'],
                         500000 + (250000 - 300000))
        self.assertEqual(res['core_rating'], 4.0)  # D29/D30: rating unmoved

    def test_fixed_band_override_stacks_with_km_scaling(self):
        v = _catalogue()
        res = calculate_core_rating(
            v, 'NSW', 3, 'pure_cost',
            {'insurance_override': 2500}, costed_km=30000)
        # 500000 stored + 700000 km re-base (dataset variable x1) - 50000
        # insurance delta.
        self.assertEqual(res['total_annual_cost'],
                         500000 + 700000 + (250000 - 300000))

    def test_fixed_band_variable_override_is_not_factor_scaled(self):
        # Servicing override is the user's own annual figure: it replaces
        # the scaled dataset line, it is not multiplied by the km factor.
        v = _catalogue()
        res = calculate_core_rating(
            v, 'NSW', 3, 'pure_cost',
            {'servicing_override': 600}, costed_km=30000)
        # stored 500000 + km re-base on dataset variable lines
        # (fuel 200000 + servicing 200000 + tyres 300000) x (2 - 1)
        # + delta (60000 user - 400000 dataset-at-costed-km).
        # Net servicing = the user's 60000, not 400000 x factor.
        self.assertEqual(res['total_annual_cost'],
                         500000 + 700000 + (60000 - 400000))

    def test_bev_energy_cycle_g_per_km_not_zero(self):
        v = _catalogue(powertrain_type='bev', tailpipe_co2_g_per_km=None,
                       energy_consumption_wh_km=200,
                       fuel_cost_by_state={}, ev_levy_by_state={},
                       electricity_cost_by_state={"NSW": 100000})
        res = calculate_core_rating(v, 'NSW', 3, 'pure_cost', {})
        self.assertEqual(res['tailpipe_co2_g_per_km'], 0.0)
        self.assertGreater(res['co2_energy_cycle_g_per_km'], 0)


class GvgMedianScalingTests(TestCase):

    def setUp(self):
        CategoryAnnualKMBenchmark.objects.create(
            fcai_category='Medium', est_annual_km=15000)
        batch = CoreDialBatch.objects.create(
            scoring_version='v6.4-b21', as_at='2026-11-03', is_current=True)
        CoreDialRow.objects.create(
            batch=batch, version_id=1, model_id='a1b2c3d4e5f6',
            state='NSW', make='Toyota', model='Camry', variant='SX',
            year=2015, fcai_category='Medium',
            driveaway_cents=20000000, coo_pa_cents=400000,
            annual_co2_kg=2000.0, co2_g_per_km=133,
            price_score=0.5, emissions_score=0.5, co2_cap=None,
            servicing_cents=100000, tyres_cents=50000,
            road_user_charge_cents=40000, ctp_cents=60000,
            comprehensive_cents=200000, registration_cents=80000,
            fuel_cents=0, electricity_cents=0)

    def _gvg(self):
        return VehicleIdentity.objects.create(
            make='Toyota', model='Camry', year=2015, variant='SX',
            body_style='sedan', fcai_category='Medium',
            powertrain_type='petrol')

    def test_km_override_scales_only_km_dependent_medians(self):
        at_benchmark = cost_gvg_current_vehicle(self._gvg(), 'NSW',
                                                annual_km=15000)
        doubled = cost_gvg_current_vehicle(self._gvg(), 'NSW',
                                           annual_km=30000)
        parts_b = at_benchmark['annual_cost_breakdown']
        parts_d = doubled['annual_cost_breakdown']
        self.assertEqual(parts_d['servicing_annual'],
                         parts_b['servicing_annual'] * 2)
        self.assertEqual(parts_d['tyres_annual'],
                         parts_b['tyres_annual'] * 2)
        self.assertEqual(parts_d['ev_levy_annual'],
                         parts_b['ev_levy_annual'] * 2)
        # Fixed medians untouched.
        self.assertEqual(parts_d['ctp_annual'], parts_b['ctp_annual'])
        self.assertEqual(parts_d['insurance_annual'],
                         parts_b['insurance_annual'])
        self.assertEqual(parts_d['registration_annual'],
                         parts_b['registration_annual'])
        self.assertEqual(doubled['annual_co2_kg'],
                         at_benchmark['annual_co2_kg'] * 2)

    def test_combustion_car_has_no_ev_road_user_charge(self):
        # B-27: the EV road-user charge applies to plug-ins only. A 1995
        # petrol Corolla's total must be exactly the six lines — fuel +
        # CTP + comprehensive + registration + servicing + tyres — with
        # the class RUC median (which mixes EV rows) dropped.
        petrol = VehicleIdentity.objects.create(
            make='Toyota', model='Corolla', year=1995, variant='SX',
            body_style='hatch', fcai_category='Medium',
            powertrain_type='petrol',
            fuel_consumption_combined_l_100km=7.5,
            tailpipe_co2_g_per_km=180)
        ed = cost_gvg_current_vehicle(petrol, 'NSW', annual_km=12100)
        bd = ed['annual_cost_breakdown']
        self.assertEqual(bd['ev_levy_annual'], 0)
        six_lines = (bd['fuel_or_energy_annual'] + bd['ctp_annual']
                     + bd['insurance_annual'] + bd['registration_annual']
                     + bd['servicing_annual'] + bd['tyres_annual'])
        self.assertEqual(ed['total_annual_cost'], six_lines)
        # CO2 is tailpipe x km / 1000 — no multiplication bug.
        self.assertEqual(ed['annual_co2_kg'], round(180 * 12100 / 1000))


class GarageKmApiTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='garage-km@carreb.com.au', password='password123',
            subscription_tier='full_insight_pro')
        self.client.force_authenticate(user=self.user)
        self.vehicle = _catalogue()
        self.purchase_date = datetime.date.today() - datetime.timedelta(days=730)
        UserPriorityState.objects.create(user=self.user, state='NSW')

    def _post_cv(self, **kwargs):
        payload = {
            'vehicle_catalogue_id': str(self.vehicle.id),
            'odometer_reading': 20000,
            'purchase_date': self.purchase_date.isoformat(),
            'state': 'NSW',
        }
        payload.update(kwargs)
        # Multipart encoding cannot carry None — drop explicitly-nulled keys.
        payload = {k: v for k, v in payload.items() if v is not None}
        return self.client.post('/api/my-garage/current-vehicle/', payload)

    def test_cv_costed_at_abs_default_despite_odometer(self):
        # Odometer + purchase date no longer derive km (retired 6-Nov-26) —
        # a fresh CV with no user km setting costs at the ABS default even
        # with both fields saved.
        resp = self._post_cv()
        self.assertEqual(resp.status_code, 200)
        engine = resp.data['engine_data']
        self.assertEqual(engine['costed_km'], GARAGE_KM_DEFAULT)
        self.assertEqual(engine['costed_km_source'], 'default')
        self.assertEqual(engine['costed_km_copy'],
                         'Costed at 12,100 km/yr (ABS 2020). '
                         'Change in Edit Vehicle.')
        self.assertFalse(engine['personalised_estimate'])
        self.assertEqual(resp.data['meta']['costed_km'], GARAGE_KM_DEFAULT)

    def test_default_copy_when_no_odometer(self):
        resp = self._post_cv(odometer_reading=None, purchase_date=None)
        engine = resp.data['engine_data']
        self.assertEqual(engine['costed_km'], GARAGE_KM_DEFAULT)
        self.assertEqual(engine['costed_km_source'], 'default')
        self.assertEqual(engine['costed_km_copy'],
                         'Costed at 12,100 km/yr (ABS 2020). '
                         'Change in Edit Vehicle.')
        self.assertFalse(engine['personalised_estimate'])

    def test_garage_km_edit_locks_and_propagates_to_every_card(self):
        self._post_cv()
        resp = self._post_cv(garage_km=25000)
        engine = resp.data['engine_data']
        self.assertEqual(engine['costed_km'], 25000)
        self.assertEqual(engine['costed_km_source'], 'user')

        # A different vehicle saved as the CV no longer re-derives from the
        # odometer — the user's setting wins.
        other = _catalogue(model='Corolla', variant='Ascent Sport',
                           mode_data_by_state={"NSW": {"B": {
                               "mode_coo_pa": 3000.0, "annual_co2_kg": 1200.0,
                               "stars": 5}}})
        resp = self._post_cv(vehicle_catalogue_id=str(other.id),
                             odometer_reading=9000)
        self.assertEqual(resp.data['engine_data']['costed_km'], 25000)

        # ...and garage cards carry the same km.
        GarageVehicle.objects.create(
            user=self.user, vehicle_catalogue=self.vehicle,
            source=GarageVehicleSource.VEHICLE_LOOKUP)
        resp = self.client.get('/api/my-garage/vehicles/')
        self.assertEqual(resp.status_code, 200)
        for card in resp.data['vehicles']:
            self.assertEqual(card['engine_data']['costed_km'], 25000)
            diff = card['engine_data']['est_cost_difference']
            self.assertEqual(diff['comparison_mode'], 'current_vehicle')

    def test_odometer_overrides_no_longer_move_costed_km(self):
        """Since the derivation was retired (Jock, 6-Nov-26), saving
        odometer/purchase_date as Edit Vehicle overrides must leave
        costed_km at the ABS default — km p.a. is set directly only."""
        self._post_cv(odometer_reading=None, purchase_date=None)
        for field, value in (('odometer_reading', '25000'),
                             ('purchase_date', '06/2023')):
            resp = self.client.patch('/api/my-garage/current-vehicle/details/',
                                     {'field_name': field, 'override_value': value},
                                     format='json')
            self.assertEqual(resp.status_code, 200)

        resp = self.client.get('/api/my-garage/current-vehicle/')
        engine = resp.data['engine_data']
        self.assertEqual(engine['costed_km'], GARAGE_KM_DEFAULT)
        self.assertEqual(engine['costed_km_source'], 'default')
        self.assertFalse(engine['personalised_estimate'])

        # Garage cards keep the same ABS default.
        GarageVehicle.objects.create(
            user=self.user, vehicle_catalogue=self.vehicle,
            source=GarageVehicleSource.VEHICLE_LOOKUP)
        resp = self.client.get('/api/my-garage/vehicles/')
        self.assertEqual(resp.data['vehicles'][0]['engine_data']['costed_km'],
                         GARAGE_KM_DEFAULT)

    def test_garage_km_guard_rails(self):
        self._post_cv()
        resp = self._post_cv(garage_km=100)  # below the typing-cap floor
        self.assertEqual(resp.status_code, 400)
        resp = self.client.patch('/api/my-garage/priority-state/',
                                 {'garage_km': 99000}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_priority_state_endpoint_roundtrip_and_unlock(self):
        resp = self.client.patch('/api/my-garage/priority-state/',
                                 {'garage_km': 20000}, format='json')
        self.assertEqual(resp.status_code, 200)
        state = resp.data['state']
        self.assertEqual(state['garage_km'], 20000)
        self.assertTrue(state['garage_km_user_set'])

        # null reverts to the ABS 2020 default.
        resp = self.client.patch('/api/my-garage/priority-state/',
                                 {'garage_km': None}, format='json')
        self.assertEqual(resp.status_code, 200)
        state = resp.data['state']
        self.assertIsNone(state['garage_km'])
        self.assertFalse(state['garage_km_user_set'])

    @mock.patch('apps.mygarage.views.emit_analytics_event')
    def test_mode_annual_costs_also_costed_at_garage_km(self, _event):
        self._post_cv(garage_km=30000)
        resp = self.client.get('/api/my-garage/current-vehicle/')
        engine = resp.data['engine_data']
        mode_costs = engine['mode_annual_costs']
        self.assertEqual(mode_costs['pure_cost'], engine['total_annual_cost'])
        # pure_cost at 30,000 km differs from the stored dataset figure.
        self.assertNotEqual(mode_costs['pure_cost'], 500000)
