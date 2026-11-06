"""B-14/B-33 finder filters: budget ceiling, exact-band star filter, and the
downward-only relaxation ladder on GET /api/vehicles/.

Contract (Jock 6-Nov): budget_max is a hard cap relaxation never crosses;
stars is an exact band (3 = rating 2.5-3.4); fewer than 5 matches steps the
budget floor down $5k at a time and the response carries the relaxation
details for the "Showing N of M" + widening-line header.
"""
from django.test import TestCase
from django.urls import reverse

from apps.vehicles.models import Vehicle


def _car(brand, model, year, driveaway_nsw, rating_nsw_b, **kw):
    defaults = dict(
        brand=brand, model=model, year=year, variant=kw.pop('variant', 'Base'),
        body_style='sedan', powertrain_type='petrol', fcai_category='Medium',
        annual_km_default=15000,
        fuel_cost_by_state={"NSW": 100000},
        insurance_estimate_by_state={"NSW": 100000},
        ctp_by_state={"NSW": 50000},
        registration_by_state={"NSW": 50000},
        servicing_5yr_estimate=500000,
        tyre_replacement_estimate=500000,
        driveaway_price_by_state={"NSW": driveaway_nsw},
        mode_data_by_state={"NSW": {"B": {
            "mode_coo_pa": 5000.0, "annual_co2_kg": 2000.0, "stars": 4.0,
            "core_rating_1dp": rating_nsw_b}}},
        is_suppressed=kw.pop('is_suppressed', False),
    )
    defaults.update(kw)
    return Vehicle.objects.create(**defaults)


class FinderFilterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.cheap = _car('Toyota', 'Camry', 2025, 30_000_00, 3.1)
        cls.mid1 = _car('Hyundai', 'Sonata', 2025, 35_000_00, 3.3)
        cls.mid2 = _car('Kia', 'K5', 2025, 38_000_00, 4.0)
        cls.mid3 = _car('Nissan', 'Altima', 2025, 32_000_00, 4.2)
        cls.mid4 = _car('Subaru', 'Liberty', 2025, 36_000_00, 4.5)
        cls.expensive = _car('BMW', 'Three', 2025, 60_000_00, 4.8)
        cls.held = _car('Aston', 'Martin', 2025, 40_000_00, 4.9,
                        is_suppressed=True)

    def _get(self, **params):
        resp = self.client.get(reverse('vehicle-list'), params)
        self.assertEqual(resp.status_code, 200)
        return resp.data

    def test_budget_max_is_a_hard_cap(self):
        data = self._get(budget_max=40000)
        names = {v['brand'] for v in data['results']}
        self.assertIn('Toyota', names)
        self.assertIn('Hyundai', names)
        self.assertIn('Kia', names)
        self.assertNotIn('BMW', names)          # above budget
        self.assertNotIn('Aston', names)        # held: never listed

    def test_star_filter_exact_band(self):
        data = self._get(stars=3)
        ratings = [v['mode_data_by_state']['NSW']['B']['core_rating_1dp']
                   for v in data['results']]
        self.assertTrue(ratings)
        for r in ratings:
            self.assertGreaterEqual(r, 2.5)
            self.assertLessEqual(r, 3.4)
        self.assertNotIn('Kia', {v['brand'] for v in data['results']})

    def test_relaxation_ladder_widens_downward_only(self):
        # Only the $60k BMW sits in 55k-65k; < 5 matches -> floor steps
        # down $5k until enough cars are in range. The ceiling never moves.
        data = self._get(budget_min=55000, budget_max=65000)
        rel = data.get('relaxation')
        self.assertIsNotNone(rel)
        self.assertTrue(rel['applied'])
        self.assertEqual(rel['widened'], 'budget_min')
        self.assertLessEqual(rel['to_dollars'], rel['from_dollars'])
        self.assertEqual(rel['strict_count'], 1)
        brands = {v['brand'] for v in data['results']}
        self.assertIn('BMW', brands)
        self.assertNotIn('Aston', brands)

    def test_no_relaxation_when_enough_matches(self):
        data = self._get(budget_min=25000, budget_max=40000)
        self.assertEqual(data.get('relaxation'), {'applied': False})
        self.assertEqual(data['count'], 5)

    def test_budget_uses_requested_state(self):
        qld_only = _car('Mazda', 'Six', 2025, 20_000_00, 4.2,
                        driveaway_price_by_state={"NSW": 90_000_00,
                                                  "QLD": 20_000_00})
        data = self._get(budget_max=25000, state='QLD')
        self.assertIn('Mazda', {v['brand'] for v in data['results']})
