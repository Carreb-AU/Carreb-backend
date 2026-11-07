"""DatasetUpload handover feature: admin upload page, task status recording.

The monthly 02-file refresh is self-service: a staff user with the
"add datasetupload" permission uploads the signed-off workbook from a
Django admin page; the Celery task records the outcome (vehicles, bounds
version, dial rows) on the upload row.
"""
import os
import tempfile

import openpyxl
from django.test import TestCase
from django.urls import reverse
from unittest import mock

from apps.users.models import User
from apps.vehicles.models import (
    CoreDialBatch, DatasetUpload, Vehicle)
from apps.vehicles.tasks import process_vehicle_excel_upload
from apps.vehicles.tests.test_consolidated_21oct import (
    HEADERS as CONSOLIDATED_HEADERS)


def _minimal_workbook(path):
    """Headers-only consolidated workbook: imports zero vehicles, syncs
    zero bounds, rebuilds an empty dial batch — a cheap end-to-end run."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Consolidated Vehicles'
    ws.append(CONSOLIDATED_HEADERS)
    bs = wb.create_sheet('CategoryScoringBounds')
    bs.append(['fcai_category', 'core_mode', 'vehicle_count',
               'cat_min_coo', 'cat_max_coo', 'actual_min_coo',
               'actual_max_coo', 'cat_min_co2', 'cat_max_co2',
               'scoring_version'])
    wb.save(path)
    return path


class DatasetUploadAdminTests(TestCase):

    def setUp(self):
        self.staff = User.objects.create_user(
            email='uploader@carreb.com.au', password='x', is_staff=True)
        self.client.force_login(self.staff)
        self.upload_url = reverse('admin:vehicles_datasetupload_upload')
        self.list_url = reverse('admin:vehicles_datasetupload_changelist')

    def test_non_staff_cannot_access(self):
        anon = User.objects.create_user(email='plain@carreb.com.au', password='x')
        self.client.force_login(anon)
        resp = self.client.get(self.upload_url)
        self.assertEqual(resp.status_code, 302)  # admin login redirect

    def test_staff_without_permission_forbidden(self):
        resp = self.client.get(self.upload_url)
        self.assertEqual(resp.status_code, 403)

    def test_staff_with_permission_can_see_form(self):
        self.staff.user_permissions.add(_perm('add_datasetupload'))
        resp = self.client.get(self.upload_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Upload the monthly dataset')

    def test_upload_creates_row_and_dispatches_task(self):
        self.staff.user_permissions.add(_perm('add_datasetupload'))
        tmp = _minimal_workbook(os.path.join(tempfile.mkdtemp(), 'in.xlsx'))
        with open(tmp, 'rb') as fh:
            with mock.patch(
                    'apps.vehicles.tasks.process_vehicle_excel_upload') as m_task:
                resp = self.client.post(
                    self.upload_url, {'file': _upload(fh, '02 test.xlsx')})
        self.assertEqual(resp.status_code, 302)
        row = DatasetUpload.objects.get()
        self.assertEqual(row.original_name, '02 test.xlsx')
        self.assertEqual(row.uploaded_by, self.staff)
        m_task.delay.assert_called_once()
        args = m_task.delay.call_args[0]
        self.assertEqual(args[1], str(row.id))

    def test_upload_rejects_non_xlsx(self):
        self.staff.user_permissions.add(_perm('add_datasetupload'))
        import io
        resp = self.client.post(
            self.upload_url,
            {'file': _upload(io.BytesIO(b'not a workbook'), 'notes.txt')})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(DatasetUpload.objects.exists())


class DatasetUploadTaskTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email='task@carreb.com.au', password='x')
        CoreDialBatch.objects.create(
            scoring_version='v-old', as_at='2026-11-01', is_current=True)
        self.tmpdir = tempfile.mkdtemp()

    def test_success_records_outcome(self):
        path = _minimal_workbook(os.path.join(self.tmpdir, 'ok.xlsx'))
        row = DatasetUpload.objects.create(
            uploaded_by=self.user, original_name='ok.xlsx')
        # Calling the task object directly runs it synchronously.
        process_vehicle_excel_upload(path, str(row.id))
        row.refresh_from_db()
        self.assertEqual(row.status, DatasetUpload.Status.SUCCESS)
        self.assertIsNotNone(row.finished_at)
        self.assertIn('dial', row.result)
        self.assertEqual(row.result['post_import_refresh'], 'ok')
        batch = CoreDialBatch.objects.get(is_current=True)
        self.assertNotEqual(batch.scoring_version, 'v-old')

    def test_failure_records_error(self):
        row = DatasetUpload.objects.create(
            uploaded_by=self.user, original_name='broken.xlsx')
        process_vehicle_excel_upload(
            os.path.join(self.tmpdir, 'missing.xlsx'), str(row.id))
        row.refresh_from_db()
        self.assertEqual(row.status, DatasetUpload.Status.FAILED)
        self.assertTrue(row.error)
        self.assertIsNotNone(row.finished_at)


def _perm(codename):
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType
    ct = ContentType.objects.get_for_model(DatasetUpload)
    return Permission.objects.get(content_type=ct, codename=codename)


def _upload(fh, name):
    from django.core.files.uploadedfile import SimpleUploadedFile
    fh.seek(0)
    return SimpleUploadedFile(name, fh.read(),
                              content_type='application/vnd.openxmlformats-'
                                           'officedocument.spreadsheetml.sheet')
