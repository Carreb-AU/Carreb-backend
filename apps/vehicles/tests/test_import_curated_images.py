"""Tests for the import_curated_images command.

Uses a fake manifest + fake PNG files on disk; no network access.
"""
import csv
import os
import tempfile
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.vehicles.management.commands.import_curated_images import silhouette_for
from apps.vehicles.models import Vehicle

MEDIA_ROOT = tempfile.mkdtemp(prefix="carreb-curated-media-")


def write_png(path, size=2048):
    """PNG well above the 6KB placeholder floor, so it looks like a real image."""
    from PIL import Image
    im = Image.new("RGB", (200, 120), (30, 60, 200))
    im.save(path, format="PNG", compress_level=0)
    assert os.path.getsize(path) > size


def make_manifest(path, rows):
    fieldnames = ["image_file", "make", "model", "year", "listing_ids", "status"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def make_vehicle(**kwargs):
    defaults = dict(
        brand="Toyota",
        model="Corolla",
        year=2026,
        variant="Ascent Sport",
        body_style="hatchback",
        fcai_category="Medium",
        powertrain_type="petrol",
    )
    defaults.update(kwargs)
    return Vehicle.objects.create(**defaults)


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ImportCuratedImagesTests(TestCase):
    def setUp(self):
        self.images_dir = tempfile.mkdtemp(prefix="carreb-curated-src-")
        self.sil_dir = tempfile.mkdtemp(prefix="carreb-curated-sil-")
        for name in ("toyota-corolla-2026.png", "toyota-corolla-2025.png",
                     "retired-model-2026.png", "silhouette-hatch.png",
                     "silhouette-suv.png"):
            write_png(os.path.join(self.images_dir, name))
        write_png(os.path.join(self.sil_dir, "silhouette-hatch.png"))
        write_png(os.path.join(self.sil_dir, "silhouette-ute.png"))
        self.manifest = os.path.join(self.images_dir, "manifest.csv")

    def run_import(self, **extra):
        opts = dict(manifest=self.manifest, images_dir=self.images_dir,
                    silhouettes_dir=self.sil_dir)
        opts.update(extra)
        return call_command("import_curated_images", **opts)

    # ------------------------------------------------------------------
    def test_silhouette_for_body_style(self):
        self.assertEqual(silhouette_for("SUV"), "silhouette-suv.png")
        self.assertEqual(silhouette_for("hatchback"), "silhouette-hatch.png")
        self.assertEqual(silhouette_for("Dual Cab Ute"), "silhouette-ute.png")
        self.assertEqual(silhouette_for("weird-style"), None)
        self.assertEqual(silhouette_for(""), None)

    def test_exact_year_match_sets_image(self):
        make_manifest(self.manifest, [
            dict(image_file="toyota-corolla-2026.png", make="Toyota",
                 model="Corolla", year=2026),
        ])
        v = make_vehicle()
        self.run_import()
        v.refresh_from_db()
        self.assertEqual(v.image_url, "/media/vehicle_images/toyota-corolla-2026.png")
        self.assertEqual(v.image_classification["source"], "curated-import")
        self.assertTrue(os.path.isfile(os.path.join(
            MEDIA_ROOT, "vehicle_images", "toyota-corolla-2026.png")))

    def test_all_variants_of_model_year_get_same_image(self):
        make_manifest(self.manifest, [
            dict(image_file="toyota-corolla-2026.png", make="Toyota",
                 model="Corolla", year=2026),
        ])
        a = make_vehicle(variant="Ascent Sport")
        b = make_vehicle(variant="ZR Hybrid")
        self.run_import()
        for v in (a, b):
            v.refresh_from_db()
            self.assertEqual(v.image_url,
                             "/media/vehicle_images/toyota-corolla-2026.png")

    def test_nearest_year_fallback_within_one_year(self):
        make_manifest(self.manifest, [
            dict(image_file="toyota-corolla-2026.png", make="Toyota",
                 model="Corolla", year=2026),
        ])
        v = make_vehicle(year=2027)
        self.run_import()
        v.refresh_from_db()
        self.assertEqual(v.image_url, "/media/vehicle_images/toyota-corolla-2026.png")

    def test_year_gap_over_one_gets_silhouette(self):
        make_manifest(self.manifest, [
            dict(image_file="toyota-corolla-2026.png", make="Toyota",
                 model="Corolla", year=2026),
        ])
        v = make_vehicle(year=2030)
        self.run_import()
        v.refresh_from_db()
        self.assertEqual(v.image_url, "/media/vehicle_images/silhouette-hatch.png")
        self.assertEqual(v.image_classification["verdict"], "silhouette")

    def test_retired_manifest_rows_are_skipped(self):
        make_manifest(self.manifest, [
            dict(image_file="retired-model-2026.png", make="Retired",
                 model="Model", year=2026, status="RETIRED"),
        ])
        v = make_vehicle(brand="Retired", model="Model")
        self.run_import()
        v.refresh_from_db()
        self.assertIsNone(v.image_url)

    def test_wipe_deletes_old_local_files(self):
        old_dir = os.path.join(MEDIA_ROOT, "vehicle_images")
        os.makedirs(old_dir, exist_ok=True)
        write_png(os.path.join(old_dir, "old-hash.jpg"))
        v = make_vehicle(image_url="/media/vehicle_images/old-hash.jpg")
        make_manifest(self.manifest, [
            dict(image_file="toyota-corolla-2026.png", make="Toyota",
                 model="Corolla", year=2026),
        ])
        self.run_import()
        self.assertFalse(os.path.exists(os.path.join(old_dir, "old-hash.jpg")))
        v.refresh_from_db()
        self.assertEqual(v.image_url,
                         "/media/vehicle_images/toyota-corolla-2026.png")

    def test_wipe_never_deletes_protected_override_files(self):
        from apps.vehicles.models import ManualVehicleEnrichment, VehicleIdentity

        old_dir = os.path.join(MEDIA_ROOT, "vehicle_images")
        os.makedirs(old_dir, exist_ok=True)
        write_png(os.path.join(old_dir, "protected.jpg"))
        v = make_vehicle(image_url="/media/vehicle_images/protected.jpg")
        identity = VehicleIdentity.objects.create(make="Toyota", model="Corolla",
                                                  year=2026, variant="Ascent Sport")
        ManualVehicleEnrichment.objects.create(
            record=identity, image_url="/media/vehicle_images/protected.jpg")
        make_manifest(self.manifest, [
            dict(image_file="toyota-corolla-2026.png", make="Toyota",
                 model="Corolla", year=2026),
        ])
        self.run_import()
        self.assertTrue(os.path.exists(os.path.join(old_dir, "protected.jpg")))

    def test_missing_manifest_image_aborts(self):
        make_manifest(self.manifest, [
            dict(image_file="does-not-exist.png", make="Toyota",
                 model="Corolla", year=2026),
        ])
        v = make_vehicle()
        self.run_import()
        v.refresh_from_db()
        self.assertIsNone(v.image_url)

    def test_dry_run_changes_nothing(self):
        old_dir = os.path.join(MEDIA_ROOT, "vehicle_images")
        os.makedirs(old_dir, exist_ok=True)
        write_png(os.path.join(old_dir, "old-hash.jpg"))
        v = make_vehicle(image_url="/media/vehicle_images/old-hash.jpg")
        make_manifest(self.manifest, [
            dict(image_file="toyota-corolla-2026.png", make="Toyota",
                 model="Corolla", year=2026),
        ])
        self.run_import(dry_run=True)
        self.assertTrue(os.path.exists(os.path.join(old_dir, "old-hash.jpg")))
        v.refresh_from_db()
        self.assertEqual(v.image_url, "/media/vehicle_images/old-hash.jpg")

    def test_unmatched_vehicle_body_style_gets_silhouette(self):
        make_manifest(self.manifest, [
            dict(image_file="toyota-corolla-2026.png", make="Toyota",
                 model="Corolla", year=2026),
        ])
        v = make_vehicle(brand="Weird", model="Mobile", body_style="hatchback")
        self.run_import()
        v.refresh_from_db()
        self.assertEqual(v.image_url, "/media/vehicle_images/silhouette-hatch.png")

    def test_unknown_body_style_is_reported_needs_image(self):
        make_manifest(self.manifest, [
            dict(image_file="toyota-corolla-2026.png", make="Toyota",
                 model="Corolla", year=2026),
        ])
        v = make_vehicle(brand="Weird", model="Mobile", body_style="amphibious")
        self.run_import()
        v.refresh_from_db()
        self.assertIsNone(v.image_url)
