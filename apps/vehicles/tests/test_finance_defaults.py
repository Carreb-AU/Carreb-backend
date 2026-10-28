"""Finance section tests: full FinanceDefaults-driven finance block.

Covers the acceptance check from the v6.4 spec review:
$41,490 car, 10% deposit, 60 months at 8.78%, no balloon -> ~$771/month,
and the "Finance - $X" header = yearly interest + fees.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.vehicles.models import Vehicle, FinanceDefault
from apps.vehicles.services.rating_engine import (
    calculate_monthly_repayment,
    get_finance_defaults_for_vehicle,
)

User = get_user_model()


def _quick_check_vehicle(**kwargs):
    defaults = dict(
        brand='Quick',
        model='Check',
        year=2025,
        variant='Base',
        body_style='sedan',
        fcai_category='Medium',
        fcai_broad='Passenger Cars',
        powertrain_type='petrol',
        num_seats=5,
        driveaway_price_by_state={'NSW': 4_149_000},  # $41,490
        mode_data_by_state={'NSW': {'B': {}, 'E': {}, 'F': {}}},
    )
    defaults.update(kwargs)
    return Vehicle.objects.create(**defaults)


class MonthlyRepaymentFormulaTests(TestCase):
    """The spec's quick check, pinned as a unit test."""

    def test_quick_check_41490_at_878_60mo(self):
        # $41,490, 10% deposit -> $37,341 financed; 8.78% p.a., 60 months.
        # Spec quick check: "about $771/month".
        monthly = calculate_monthly_repayment(37_341.0, 8.78, 60)
        self.assertAlmostEqual(monthly, 771.16, places=1)

    def test_balloon_reduces_monthly(self):
        without = calculate_monthly_repayment(37_341.0, 8.78, 60)
        with_balloon = calculate_monthly_repayment(37_341.0, 8.78, 60, balloon_value=7_468.20)
        self.assertLess(with_balloon, without)
        # A 20% balloon on a 60-month term at 0% should be exactly (P-B)/n
        self.assertAlmostEqual(
            calculate_monthly_repayment(37_341.0, 0.0, 60, balloon_value=7_468.20),
            (37_341.0 - 7_468.20) / 60, places=2)

    def test_zero_months_is_zero(self):
        self.assertEqual(calculate_monthly_repayment(10_000, 8.78, 0), 0.0)


class FinanceDefaultsHelperTests(TestCase):
    def setUp(self):
        self.fin = FinanceDefault.objects.create(
            fcai_category_broad='Passenger Cars',
            deposit_pct=10.0,
            base_rate_pct=8.78,
            alt_fuel_modifier_pct=-0.5,
            term_months=60,
            balloon_pct=0.0,
            estab_fee_default=40000,
            estab_fee_bev=30000,
            admin_fee_monthly=1000,
        )

    def test_maps_broad_category(self):
        vehicle = _quick_check_vehicle()
        self.assertEqual(get_finance_defaults_for_vehicle(vehicle), self.fin)

    def test_falls_back_to_category_guess(self):
        vehicle = _quick_check_vehicle(fcai_broad='', fcai_category='Medium SUV')
        self.assertEqual(get_finance_defaults_for_vehicle(vehicle), self.fin)


class LookupFinanceBlockTests(TestCase):
    """GET /api/vehicles/lookup/ returns the full finance field set."""

    def setUp(self):
        self.client = APIClient()
        FinanceDefault.objects.create(
            fcai_category_broad='Passenger Cars',
            deposit_pct=10.0,
            base_rate_pct=8.78,
            alt_fuel_modifier_pct=-0.5,
            term_months=60,
            balloon_pct=0.0,
            estab_fee_default=40000,
            estab_fee_bev=30000,
            admin_fee_monthly=1000,
        )
        self.vehicle = _quick_check_vehicle()

    def _lookup(self):
        resp = self.client.get('/api/vehicles/lookup/', {'name': '2025 Quick Check', 'state': 'NSW'})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get('success'), body)
        return body['finance']

    def test_full_finance_block_defaults(self):
        fin = self._lookup()
        self.assertEqual(fin['deposit_pct'], 10.0)
        self.assertEqual(fin['deposit_amount'], 4149.0)
        self.assertEqual(fin['loan_amount'], 37341.0)
        self.assertEqual(fin['loan_term_months'], 60)
        self.assertEqual(fin['interest_rate_pct'], 8.78)
        self.assertEqual(fin['balloon_pct'], 0.0)
        self.assertEqual(fin['balloon_amount'], 0.0)
        self.assertAlmostEqual(fin['monthly_repayment'], 771.16, delta=0.05)
        self.assertEqual(fin['monthly_repayment_display'], '$771')
        # Yearly interest + fees: (771.16*60 - 37341)/5 + ($400 + $10*60)/5
        self.assertAlmostEqual(fin['finance_cost_pa'], 1985.68, delta=0.1)
        self.assertEqual(fin['finance_cost_pa_display'], '$1,986')
        self.assertEqual(fin['estab_fee'], 400.0)
        self.assertEqual(fin['admin_fee_monthly'], 10.0)

    def test_alt_fuel_modifier_applies_to_bev(self):
        self.vehicle.powertrain_type = 'bev'
        self.vehicle.driveaway_price_by_state = {'NSW': 4_149_000}
        self.vehicle.save()
        fin = self._lookup()
        self.assertEqual(fin['interest_rate_pct'], 8.28)
        # BEV establishment fee tier
        self.assertEqual(fin['estab_fee'], 300.0)


class RatingEngineFinanceFallbackTests(TestCase):
    """Modes E/F use FinanceDefaults (not hardcoded 80%/7.5%/60) when the
    workbook has no stored finance_cost_pa, and honour user_inputs overrides."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='paid@carreb.com.au', password='x', subscription_tier='paid')
        self.client.force_authenticate(user=self.user)
        FinanceDefault.objects.create(
            fcai_category_broad='Passenger Cars',
            deposit_pct=10.0,
            base_rate_pct=8.78,
            alt_fuel_modifier_pct=-0.5,
            term_months=60,
            balloon_pct=0.0,
            estab_fee_default=40000,
            estab_fee_bev=30000,
            admin_fee_monthly=1000,
        )
        # No stored finance/resale values anywhere in mode data
        self.vehicle = _quick_check_vehicle()

    def _calculate(self, user_inputs=None):
        payload = {
            'vehicle_id': str(self.vehicle.id),
            'state': 'NSW',
            'priority_slider': 3,
            'core_mode': 'cool_choice',
            'user_inputs': user_inputs or {},
        }
        resp = self.client.post('/api/core-rating/calculate/', data=payload, format='json')
        self.assertEqual(resp.status_code, 200, resp.json())
        return resp.json()['data']

    def _finance_annual(self, user_inputs=None):
        data = self._calculate(user_inputs)
        return data['annual_cost_breakdown']['finance_annual']

    def test_finance_annual_is_yearly_interest_plus_fees(self):
        # ~$1,985.68/yr -> cents
        self.assertAlmostEqual(self._finance_annual(), 198_568, delta=200)

    def test_user_inputs_override_rate_and_deposit(self):
        # 0% interest, no deposit -> finance cost = fees only
        data = self._calculate({'interest_rate': 0.0, 'deposit_pct': 0.0})
        fees_pa = (10.0 * 12 + 400.0 / 5)
        self.assertAlmostEqual(data['annual_cost_breakdown']['finance_annual'],
                               fees_pa * 100, delta=150)

    def test_user_inputs_balloon_reduces_finance_cost(self):
        no_balloon = self._finance_annual()
        with_balloon = self._finance_annual({'balloon_pct': 30.0})
        self.assertLess(with_balloon, no_balloon)
