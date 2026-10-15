"""CORE Dial (v6.4) tests.

Includes the golden acceptance cases from the build prompt (section 9),
run against the source workbook when it is present (skipped otherwise),
plus unit and endpoint tests on synthetic data.
"""
import math
import os
import statistics
import unittest
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.vehicles.models import CoreDialBatch, CoreDialRow, Vehicle
from apps.vehicles.services.core_dial import (
    BAND_NAMES,
    PRIORITY_STOPS,
    budget_range_line,
    budget_window_cents,
    compute_bands,
    dollars_to_cents,
    initial_needle_band,
    is_valid_budget,
    matches_header,
    rate_version,
    round_half_up,
    select_matches,
)
from apps.vehicles.services.core_dial_import import parse_workbook

User = get_user_model()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
GOLDEN_WORKBOOK = os.path.join(
    BASE_DIR, 'docs',
    '02 Vehicles & CORE (v6.3.4 Data, New Vehicles FY26, VehicleCOREScore_Canonical, '
    'CategoryScoringBounds) - 07-Oct-26.xlsx',
)


def make_row(version_id, model_id, make, driveaway, coo, co2kg,
             price_score, emissions_score, co2_cap=None):
    return SimpleNamespace(
        version_id=version_id,
        model_id=model_id,
        make=make,
        driveaway_cents=dollars_to_cents(driveaway),
        coo_pa_cents=dollars_to_cents(coo),
        annual_co2_kg=co2kg,
        price_score=price_score,
        emissions_score=emissions_score,
        co2_cap=co2_cap,
    )


class RoundingTests(TestCase):
    def test_round_half_up_halves(self):
        self.assertEqual(round_half_up(4.5, 0), 5)
        self.assertEqual(round_half_up(2.5, 0), 3)
        self.assertEqual(round_half_up(0.5, 0), 1)
        self.assertEqual(round_half_up(2.45, 1), 2.5)
        # Python round() would give 4 for the first two — that is the bug.

    def test_dollars_to_cents_half_up(self):
        self.assertEqual(dollars_to_cents(635.735), 63574)  # 63573.5 -> half up
        self.assertEqual(dollars_to_cents(6714.04), 671404)

    def test_rating_trap_byd_atto3_balanced(self):
        # rates 4.5 at Balanced -> band 5 (Python round() gives 4 — wrong)
        rating, band = rate_version(0.9, 0.9, None, 3)
        self.assertEqual(rating, 4.5)
        self.assertEqual(band, 5)

    def test_rating_trap_audi_a4_stop1(self):
        # rates 2.5 at stop 1 -> band 3 (Python gives 2 — wrong)
        rating, band = rate_version(0.5, 0.5, None, 1)
        self.assertEqual(rating, 2.5)
        self.assertEqual(band, 3)

    def test_rating_trap_mustang_cap(self):
        # 250 g/km: rates 2.5, capped to 2.4 -> band 2
        rating, band = rate_version(0.5, 0.5, 2.4, 1)
        self.assertEqual(rating, 2.4)
        self.assertEqual(band, 2)

    def test_reference_figure_alfa_giulia(self):
        # Spec section 11: 2025 Alfa Romeo Giulia Quadrifoglio, stop 1
        rating, band = rate_version(0.405697, 0.426136, None, 1)
        self.assertEqual(rating, 2.0)
        self.assertEqual(band, 2)
        self.assertEqual(BAND_NAMES[band], 'The Detour™')

    def test_co2_cap_tiers(self):
        from apps.vehicles.services.core_dial import co2_cap_for
        self.assertEqual(co2_cap_for('petrol', 250), 2.4)
        self.assertEqual(co2_cap_for('petrol', 249), 3.4)
        self.assertEqual(co2_cap_for('petrol', 200), 3.4)
        self.assertEqual(co2_cap_for('petrol', 199), 4.4)
        self.assertEqual(co2_cap_for('petrol', 150), 4.4)
        self.assertIsNone(co2_cap_for('petrol', 149))
        self.assertIsNone(co2_cap_for('bev', 999))
        self.assertIsNone(co2_cap_for('fcev', 999))


class BudgetWindowTests(TestCase):
    def test_window_60000(self):
        lo, hi = budget_window_cents(60000)
        self.assertEqual((lo, hi), (dollars_to_cents(45000), dollars_to_cents(75000)))

    def test_window_top(self):
        lo, hi = budget_window_cents(200000)
        self.assertEqual(lo, dollars_to_cents(185000))
        self.assertIsNone(hi)

    def test_window_bounds_inclusive(self):
        rows = [
            make_row(1, 'a', 'X', 45000, 5000, 1000, 0.5, 0.5),
            make_row(2, 'b', 'X', 75000, 5000, 1000, 0.5, 0.5),
            make_row(3, 'c', 'X', 44999, 5000, 1000, 0.5, 0.5),
            make_row(4, 'd', 'X', 75001, 5000, 1000, 0.5, 0.5),
        ]
        bands = compute_bands(rows, 60000, 3)
        total = sum(b['count'] for b in bands.values())
        self.assertEqual(total, 2)

    def test_range_lines(self):
        self.assertEqual(budget_range_line(60000), 'Cars priced $45,000–$75,000')
        self.assertEqual(budget_range_line(20000), 'Cars priced up to $35,000')
        self.assertEqual(budget_range_line(200000), 'Cars priced $185,000 and up')

    def test_budget_validation(self):
        self.assertTrue(is_valid_budget(20000))
        self.assertTrue(is_valid_budget(200000))
        self.assertTrue(is_valid_budget(60000))
        self.assertFalse(is_valid_budget(19999))
        self.assertFalse(is_valid_budget(200001))
        self.assertFalse(is_valid_budget(60001))
        self.assertFalse(is_valid_budget(None))
        self.assertFalse(is_valid_budget('60000'))


class BandComputationTests(TestCase):
    def _rows(self):
        # Two models, two versions each; ratings at stop 1 put v1/band3 & v2/band2
        return [
            make_row(1, 'm1', 'MakeA', 50000, 5200.0, 2000, 0.5, 0.4),
            make_row(2, 'm1', 'MakeA', 52000, 5400.0, 2000, 0.45, 0.4),  # worse rating
            make_row(3, 'm2', 'MakeB', 55000, 5000.0, 1000, 0.52, 0.5),
            make_row(4, 'm2', 'MakeB', 58000, 5000.0, 1000, 0.52, 0.5),
            make_row(5, 'm3', 'MakeC', 60000, 3000.0, 0, 0.9, 0.9),
        ]

    def test_collapse_keeps_top_version_per_model(self):
        bands = compute_bands(self._rows(), 60000, 1)
        counts = {b: bands[b]['count'] for b in bands}
        self.assertEqual(sum(counts.values()), 3)  # 3 models, once each

    def test_model_counts_in_two_bands(self):
        # Same model rated into two bands counts in both (spec 6.1)
        rows = [
            make_row(1, 'm1', 'MakeA', 50000, 5000, 1000, 0.9, 0.9),   # band 5
            make_row(2, 'm1', 'MakeA', 70000, 5000, 1000, 0.5, 0.5),   # band 3
        ]
        bands = compute_bands(rows, 60000, 1)
        self.assertEqual(bands[5]['count'], 1)
        self.assertEqual(bands[3]['count'], 1)

    def test_medians_odd_and_even(self):
        rows = [
            make_row(1, 'm1', 'A', 50000, 4000, 100, 0.5, 0.5),
            make_row(2, 'm2', 'B', 50000, 5000, 200, 0.5, 0.5),
            make_row(3, 'm3', 'C', 50000, 6000, 300, 0.5, 0.5),
        ]
        bands = compute_bands(rows, 50000, 1)
        # all rate 2.5 -> band 3
        b = bands[3]
        self.assertEqual(b['count'], 3)
        self.assertEqual(b['coo_pa_cents'], dollars_to_cents(5000))
        self.assertEqual(b['annual_co2_kg'], 200)

        rows2 = rows + [make_row(4, 'm4', 'D', 50000, 8000, 400, 0.5, 0.5)]
        b = compute_bands(rows2, 50000, 1)[3]
        self.assertEqual(b['coo_pa_cents'], dollars_to_cents(5500))  # mean of middle two
        self.assertEqual(b['annual_co2_kg'], 250)

    def test_co2_median_independent_of_coo_median(self):
        rows = [
            make_row(1, 'm1', 'A', 50000, 4000, 900, 0.5, 0.5),
            make_row(2, 'm2', 'B', 50000, 6000, 100, 0.5, 0.5),
        ]
        b = compute_bands(rows, 50000, 1)[3]
        self.assertEqual(b['coo_pa_cents'], dollars_to_cents(5000))
        self.assertEqual(b['annual_co2_kg'], 500)  # not the CO2 of the median-COO car

    def test_initial_needle_highest_nonempty(self):
        rows = self._rows()
        bands = compute_bands(rows, 60000, 1)
        self.assertEqual(initial_needle_band(bands), 5)  # m3 lands highest

    def test_initial_needle_all_empty(self):
        bands = {b: {'count': 0, 'models': [], 'coo_pa_cents': None, 'annual_co2_kg': None}
                 for b in range(1, 6)}
        self.assertEqual(initial_needle_band(bands), 3)


class MatchesSelectionTests(TestCase):
    def test_fill_passes_one_then_two_per_make(self):
        rows = [
            make_row(i + 1, f'm{i}', f'Make{chr(65 + i)}', 50000, 5000, 100, 0.5, 0.5)
            for i in range(6)
        ]
        # plus a second model for MakeA and MakeB
        rows += [
            make_row(7, 'm0b', 'MakeA', 51000, 5000, 100, 0.5, 0.5),
            make_row(8, 'm1b', 'MakeB', 51000, 5000, 100, 0.5, 0.5),
        ]
        bands = compute_bands(rows, 50000, 1)
        models = bands[3]['models']
        picked = select_matches(models, limit=10)
        self.assertEqual(len(picked), 8)  # never padded
        makes = [m['row'].make for m in picked]
        self.assertEqual(makes[:6], ['MakeA', 'MakeB', 'MakeC', 'MakeD', 'MakeE', 'MakeF'])
        self.assertEqual(makes[6:], ['MakeA', 'MakeB'])

    def test_header_strings(self):
        self.assertEqual(matches_header(0, 0), None)
        self.assertEqual(matches_header(1, 1), 'Showing 1 match')
        self.assertEqual(matches_header(4, 4), 'Showing all 4 matches')
        self.assertEqual(matches_header(36, 10), 'Showing 10 of 36 matches')


class CoreDialApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='dial@carreb.com.au', password='password123',
            subscription_tier='car_buying_sprint',
        )
        self.free_user = User.objects.create_user(
            email='free@carreb.com.au', password='password123',
            subscription_tier='free',
        )
        self.batch = CoreDialBatch.objects.create(
            scoring_version='v6.4-test', as_at='2026-10-07', is_current=True,
        )
        vehicle = Vehicle.objects.create(
            brand='Zeekr', model='X', variant='RWD', year=2024,
            body_style='SUV', powertrain_type='bev',
            fcai_category='Small SUV', test_cycle='WLTP',
            driveaway_price_by_state={'NSW': 5000000},
            image_url='https://example.test/img.png',
        )
        self.rows = []
        for i, (mk, mdl, dw, coo) in enumerate([
            ('Alpha', 'One', 50000, 4000), ('Alpha', 'Two', 52000, 4200),
            ('Beta', 'One', 54000, 4400), ('Gamma', 'One', 56000, 4600),
        ], start=1):
            self.rows.append(CoreDialRow.objects.create(
                batch=self.batch, version_id=i,
                model_id=f'{i:012x}'[:12],
                vehicle=vehicle if i == 1 else None,
                state='NSW', make=mk, model=mdl, variant='v', year=2024,
                fcai_category='Small SUV',
                driveaway_cents=dollars_to_cents(dw),
                coo_pa_cents=dollars_to_cents(coo),
                annual_co2_kg=0.0, co2_g_per_km=0,
                price_score=0.9, emissions_score=0.9, co2_cap=None,
            ))

    def _auth(self, user=None):
        self.client.force_authenticate(user=user or self.user)

    # --- dataset ---

    def test_dataset_requires_auth(self):
        resp = self.client.get('/api/core-dial/dataset/', {'state': 'NSW'})
        self.assertEqual(resp.status_code, 401)

    def test_dataset_bad_state(self):
        self._auth()
        resp = self.client.get('/api/core-dial/dataset/', {'state': 'XXX'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'invalid_params')

    def test_dataset_shape_no_names(self):
        self._auth()
        resp = self.client.get('/api/core-dial/dataset/', {'state': 'NSW'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['scoring_version'], 'v6.4-test')
        self.assertEqual(resp.data['state'], 'NSW')
        self.assertEqual(len(resp.data['rows']), 4)
        row = resp.data['rows'][0]
        self.assertEqual(row['version_id'], 1)
        for forbidden in ('make', 'model', 'variant', 'year', 'vehicle_id'):
            self.assertNotIn(forbidden, row)
        self.assertEqual(set(row['parts_cents'].keys()), {
            'fuel', 'electricity', 'ctp', 'comprehensive', 'registration',
            'servicing', 'tyres', 'road_user_charge',
        })
        self.assertIn('ETag', resp.headers)
        self.assertIn('v6.4-test:NSW', resp.headers['ETag'])
        self.assertEqual(resp.headers.get('Cache-Control'), 'private')

    def test_dataset_etag_304(self):
        self._auth()
        resp = self.client.get('/api/core-dial/dataset/', {'state': 'NSW'})
        etag = resp.headers['ETag']
        resp2 = self.client.get('/api/core-dial/dataset/', {'state': 'NSW'},
                                HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(resp2.status_code, 304)

    def test_dataset_free_user_ok(self):
        self._auth(self.free_user)
        resp = self.client.get('/api/core-dial/dataset/', {'state': 'NSW'})
        self.assertEqual(resp.status_code, 200)

    # --- matches ---

    def _matches(self, user=None, **params):
        base = {'state': 'NSW', 'budget': 60000, 'stop': 1, 'band': 5,
                'v': 'v6.4-test'}
        base.update(params)
        return self.client.get('/api/core-dial-matches/', base)

    def test_matches_requires_auth(self):
        resp = self._matches()
        self.assertEqual(resp.status_code, 401)

    def test_matches_free_user_upgrade_required(self):
        self._auth(self.free_user)
        resp = self._matches()
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data['error'], 'upgrade_required')

    def test_matches_invalid_params(self):
        self._auth()
        for params in ({'state': 'XX'}, {'budget': 60001}, {'budget': 10000},
                       {'stop': 0}, {'stop': 6}, {'band': 6}, {'v': ''}):
            resp = self._matches(**params)
            self.assertEqual(resp.status_code, 400, params)
            self.assertEqual(resp.data['error'], 'invalid_params')

    def test_matches_dataset_stale(self):
        self._auth()
        resp = self._matches(v='v6.3-old')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data['error'], 'dataset_stale')
        self.assertEqual(resp.data['scoring_version'], 'v6.4-test')

    def test_matches_total_equals_dial_count(self):
        self._auth()
        resp = self._matches()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['total'], 4)
        self.assertEqual(resp.data['shown'], 4)
        self.assertEqual(resp.data['header'], 'Showing all 4 matches')
        card = resp.data['results'][0]
        self.assertEqual(card['make'], 'Alpha')
        self.assertEqual(card['rating'], 4.5)
        self.assertEqual(card['coo_pa_cents'], dollars_to_cents(4000))
        self.assertEqual(card['image_url'], 'https://example.test/img.png')
        for key in ('vehicle_id', 'year', 'model', 'variant', 'band',
                    'co2_g_km', 'driveaway_cents', 'price_basis'):
            self.assertIn(key, card)

    def test_matches_empty_band(self):
        self._auth()
        resp = self._matches(band=1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['total'], 0)
        self.assertEqual(resp.data['shown'], 0)
        self.assertIsNone(resp.data['header'])
        self.assertEqual(resp.data['results'], [])

    def test_priority_state_patch_semantics(self):
        user = User.objects.create_user(
            email='patch@carreb.com.au', password='password123',
            subscription_tier='free',
        )
        self._auth(user)
        resp = self.client.patch('/api/my-garage/priority-state/',
                                 {'priority_slider_position': 3, 'budget_max': 60000,
                                  'state': 'nsw'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.data.keys()), {'state'})
        self.assertEqual(resp.data['state']['state'], 'NSW')
        self.assertEqual(resp.data['state']['priority_slider_position'], 3)
        self.assertEqual(resp.data['state']['budget_max'], 60000)

        for bad in ({'budget_max': 12345}, {'budget_max': 10000},
                    {'state': 'XXX'}, {'priority_slider_position': 0}):
            resp = self.client.patch('/api/my-garage/priority-state/', bad, format='json')
            self.assertEqual(resp.status_code, 400, bad)

        resp = self.client.patch('/api/my-garage/priority-state/',
                                 {'budget_max': None}, format='json')
        self.assertEqual(resp.status_code, 200)

    def test_matches_throttled(self):
        from django.core.cache import cache
        cache.clear()
        user = User.objects.create_user(
            email='throttle@carreb.com.au', password='password123',
            subscription_tier='car_buying_sprint',
        )
        self._auth(user)
        last = None
        for _ in range(20):
            last = self._matches()
        self.assertEqual(last.status_code, 200)
        resp = self._matches()
        self.assertEqual(resp.status_code, 429)


@unittest.skipUnless(os.path.exists(GOLDEN_WORKBOOK),
                     'source workbook not present')
class GoldenWorkbookTests(TestCase):
    """Section 9 acceptance cases, to the dollar, from the source workbook."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.parsed = parse_workbook(GOLDEN_WORKBOOK, as_at='2026-10-07')
        cls.rows = {st: [] for st in ('ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA')}
        for r in cls.parsed.dial_rows():
            cls.rows[r.state].append(r)

    def test_dataset_size(self):
        self.assertEqual(len(self.parsed.listings), 1202)
        for st in self.rows:
            self.assertEqual(len(self.rows[st]), 1173, st)

    def test_golden_case_nsw_60000_stop1(self):
        bands = compute_bands(self.rows['NSW'], 60000, 1)
        expected = {
            1: (36, 6203, 2958, -1203),
            2: (75, 5754, 2475, -754),
            3: (34, 5259, 1965, -259),
            4: (42, 4494, 0, 506),
            5: (22, 4022, 302, 978),
        }
        for b, (n, coo_d, co2_d, diff_d) in expected.items():
            data = bands[b]
            self.assertEqual(data['count'], n, f'band {b} count')
            self.assertEqual(round_half_up(data['coo_pa_cents'] / 100, 0), coo_d, f'band {b} coo')
            self.assertEqual(round_half_up(data['annual_co2_kg'], 0), co2_d, f'band {b} co2')
            self.assertEqual(
                round_half_up((500000 - data['coo_pa_cents']) / 100, 0), diff_d,
                f'band {b} diff')

    def test_golden_needle_breakdown(self):
        bands = compute_bands(self.rows['NSW'], 60000, 1)
        self.assertEqual(initial_needle_band(bands), 5)
        models = sorted(bands[5]['models'],
                        key=lambda m: (m['row'].coo_pa_cents, m['row'].version_id))
        mid = models[len(models) // 2]['row']
        self.assertEqual((mid.year, mid.make, mid.model), (2024, 'Zeekr', 'X'))
        expected_parts = {
            'electricity': 63573, 'ctp': 57200, 'comprehensive': 181634,
            'registration': 47500, 'servicing': 34590, 'tyres': 17680,
            'fuel': 0, 'road_user_charge': 0,
        }
        self.assertEqual(mid.parts_cents, expected_parts)
        self.assertEqual(mid.coo_pa_cents, sum(expected_parts.values()))

    def test_golden_case_200k_steady_cruiser(self):
        bands = compute_bands(self.rows['NSW'], 200000, 1)
        b3 = bands[3]
        self.assertEqual(b3['count'], 4)
        self.assertEqual(round_half_up(b3['coo_pa_cents'] / 100, 0), 6480)
        self.assertEqual(round_half_up(b3['annual_co2_kg'], 0), 3185)
        self.assertEqual(round_half_up((500000 - b3['coo_pa_cents']) / 100, 0), -1480)
        names = {(m['row'].make, m['row'].model) for m in b3['models']}
        self.assertEqual(names, {
            ('Porsche', '718'), ('Aston Martin', 'Vantage'),
            ('Jaguar', 'F-TYPE'), ('Land Rover', 'Range Rover'),
        })
        picked = select_matches(b3['models'])
        self.assertEqual(len(picked), 4)
        self.assertEqual(matches_header(b3['count'], len(picked)),
                         'Showing all 4 matches')

    def test_golden_case_150k_mostly_green_band1_empty(self):
        bands = compute_bands(self.rows['NSW'], 150000, 5)
        self.assertEqual(bands[1]['count'], 0)

    def test_golden_case_200k_captain_carbon_fill(self):
        bands = compute_bands(self.rows['NSW'], 200000, 1)
        b1 = bands[1]
        self.assertEqual(b1['count'], 12)
        picked = select_matches(b1['models'])
        self.assertEqual(len(picked), 8)
        self.assertEqual(matches_header(b1['count'], len(picked)),
                         'Showing 8 of 12 matches')

    def test_national_ratings_identical_across_states(self):
        # Same car in any two states -> identical rating and band (rule 2)
        by_key = {}
        for st in ('NSW', 'VIC'):
            for r in self.rows[st]:
                by_key.setdefault((r.make, r.model, r.variant, r.year), {})[st] = r
        checked = 0
        for key, states in by_key.items():
            if len(states) < 2 or checked >= 50:
                continue
            r1, r2 = states['NSW'], states['VIC']
            self.assertEqual((r1.price_score, r1.emissions_score),
                             (r2.price_score, r2.emissions_score), key)
            self.assertEqual(rate_version(r1.price_score, r1.emissions_score, r1.co2_cap, 1),
                             rate_version(r2.price_score, r2.emissions_score, r2.co2_cap, 1), key)
            checked += 1
