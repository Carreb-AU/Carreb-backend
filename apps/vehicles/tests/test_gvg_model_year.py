"""B-01: GVG model-year (MY) labels must be stored, searchable, and carded.

The GVG release version (e.g. "MY25") can differ from the release year
(year=2024) — searching "zeekr 009 2025" previously found nothing and
fell through to the AI lookup.
"""
import os
import tempfile

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from unittest import mock

from apps.vehicles.models import VehicleIdentity
from apps.vehicles.services.gvg_import import (
    identity_search_text,
    import_gvg_xlsx,
    model_year_from_label,
)


class ModelYearLabelTests(TestCase):
    def test_my_label_parses_to_year(self):
        self.assertEqual(model_year_from_label('MY25'), 2025)
        self.assertEqual(model_year_from_label('my 24'), 2024)
        self.assertEqual(model_year_from_label('MY2025'), 2025)
        # Chassis-style labels carry no model year.
        self.assertIsNone(model_year_from_label('VJ'))
        self.assertIsNone(model_year_from_label(''))

    def test_search_text_includes_my_and_derived_year(self):
        text = identity_search_text(2024, 'ZEEKR', '009', '6 Seat AWD', 'MY25')
        self.assertIn('my25', text)
        self.assertIn('2025', text)
        # Without an MY label the text is just the plain tokens.
        plain = identity_search_text(2015, 'Toyota', 'Camry', 'Altise', '')
        self.assertEqual(plain, '2015 toyota camry altise')


class GvgModelYearImportTests(TestCase):
    _COLUMNS = [
        'ModelReleaseYear', 'Make', 'ModelReleaseVersion', 'Model', 'Variant',
        'EngineDisplacement', 'TransmissionTypeDescription', 'SeatingCapacity',
        'BodyStyle', 'FuelType', 'CO2EmissionsCombined',
        'FuelConsumptionCombined', 'EnergyConsumptionWhkm', 'ElectricRangeKm',
        'IsCurrentModel', 'ModelEndYear', 'Test Cycle', 'AnnualFuelCost',
    ]

    def _import_rows(self, rows):
        import pandas as pd
        df = pd.DataFrame(rows, columns=self._COLUMNS)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'gvg.xlsx')
            with pd.ExcelWriter(path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Vehicles 2004-2025',
                            index=False)
            return import_gvg_xlsx(path)

    def test_importer_stores_model_year_and_searable_text(self):
        res = self._import_rows([{
            'ModelReleaseYear': 2024, 'Make': 'ZEEKR', 'ModelReleaseVersion':
            'MY25', 'Model': '009', 'Variant': '6 Seat AWD',
            'EngineDisplacement': '', 'TransmissionTypeDescription': '',
            'SeatingCapacity': 6, 'BodyStyle': 'SUV', 'FuelType':
            'Electric', 'CO2EmissionsCombined': 0,
            'FuelConsumptionCombined': '', 'EnergyConsumptionWhkm': 205,
            'ElectricRangeKm': 582, 'IsCurrentModel': 'yes',
            'ModelEndYear': '', 'Test Cycle': 'WLTP', 'AnnualFuelCost': '',
        }])
        rec = VehicleIdentity.objects.get(make='ZEEKR')
        self.assertEqual(rec.year, 2024)
        self.assertEqual(rec.model_year, 'MY25')
        self.assertIn('2025', rec.search_text)


class GvgModelYearSearchTests(TestCase):
    """The current-vehicle search must match a year token against the
    MY-derived year, and must not fall through to the AI lookup."""

    ENDPOINT = reverse('current-vehicle-search')

    def setUp(self):
        self.client = APIClient()
        VehicleIdentity.objects.create(
            make='ZEEKR', model='009', year=2024, variant='6 Seat AWD',
            model_year='MY25', body_style='suv', powertrain_type='bev',
            fuel_type_raw='Electric',
            search_text=identity_search_text(2024, 'ZEEKR', '009',
                                             '6 Seat AWD', 'MY25'),
            source_dataset='GVG-CURRENT', test_cycle='WLTP')

    @mock.patch('apps.mygarage.views.search_ai_vehicles')
    def test_year_token_matches_my_label(self, m_ai):
        resp = self.client.post(self.ENDPOINT,
                                {'query': 'zeekr 009 2025'}, format='json')
        self.assertEqual(resp.status_code, 200)
        gvg_rows = [r for r in resp.data if r.get('source') == 'gvg']
        self.assertEqual(len(gvg_rows), 1)
        self.assertEqual(gvg_rows[0]['model_year'], 'MY25')
        m_ai.assert_not_called()

    @mock.patch('apps.mygarage.views.search_ai_vehicles')
    def test_release_year_still_matches(self, m_ai):
        resp = self.client.post(self.ENDPOINT,
                                {'query': 'zeekr 009 2024'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(r.get('source') == 'gvg' for r in resp.data))
        m_ai.assert_not_called()

