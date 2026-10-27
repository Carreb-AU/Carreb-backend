"""Tests for the vehicle image-quality pipeline.

Covers heuristic_check, is_blacklisted, and the classify / cleanup / scrape
management commands with all AI and network boundaries mocked. No network
access anywhere in this module.
"""
import io
import os
import random
import shutil
import tempfile
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.vehicles.models import Vehicle
from apps.vehicles.services import image_ai


def make_solid_png(width=640, height=400, color=(200, 30, 30), level=0):
    """Solid-colour PNG; compress_level=0 keeps it well above the 6KB floor."""
    from PIL import Image

    im = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    im.save(buf, format="PNG", compress_level=level)
    return buf.getvalue()


def make_noise_jpeg(width=800, height=500, seed=42):
    """Random-noise JPEG — should always pass the heuristic screen (None)."""
    from PIL import Image

    rng = random.Random(seed)
    im = Image.new("RGB", (width, height))
    im.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                for _ in range(width * height)])
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def make_transparent_png(width=800, height=500, level=0):
    from PIL import Image

    im = Image.new("RGBA", (width, height), (40, 40, 40, 255))
    for y in range(height):
        for x in range(width // 2):
            im.putpixel((x, y), (40, 40, 40, 0))
    buf = io.BytesIO()
    im.save(buf, format="PNG", compress_level=level)
    return buf.getvalue()


def make_vehicle(**kwargs):
    defaults = dict(
        brand="TestMake",
        model="TestModel",
        year=2025,
        variant="Base",
        fcai_category="Medium",
        powertrain_type="petrol",
    )
    defaults.update(kwargs)
    return Vehicle.objects.create(**defaults)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="carreb-test-media-"))
class ImageServicesTests(TestCase):
    def test_heuristic_tiny_file_is_placeholder(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (10, 10), (255, 0, 0)).save(buf, format="PNG")
        result = image_ai.heuristic_check(buf.getvalue())
        self.assertEqual(result["verdict"], "placeholder")

    def test_heuristic_small_dimensions_are_placeholder(self):
        # Noise so the file exceeds 6KB; dimensions below 400x250.
        from PIL import Image

        rng = random.Random(1)
        im = Image.new("RGB", (300, 200))
        im.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                    for _ in range(300 * 200)])
        buf = io.BytesIO()
        im.save(buf, format="PNG", compress_level=0)
        self.assertGreater(len(buf.getvalue()), 6 * 1024)
        result = image_ai.heuristic_check(buf.getvalue())
        self.assertEqual(result["verdict"], "placeholder")

    def test_heuristic_solid_colour_is_silhouette(self):
        self.assertGreater(len(make_solid_png()), 6 * 1024)
        result = image_ai.heuristic_check(make_solid_png())
        self.assertEqual(result["verdict"], "silhouette")

    def test_heuristic_transparency_is_silhouette(self):
        result = image_ai.heuristic_check(make_transparent_png())
        self.assertEqual(result["verdict"], "silhouette")

    def test_heuristic_noise_jpeg_passes(self):
        result = image_ai.heuristic_check(make_noise_jpeg())
        self.assertIsNone(result)

    def test_heuristic_undecodable_is_placeholder(self):
        result = image_ai.heuristic_check(b"this is not an image" * 500)
        self.assertEqual(result["verdict"], "placeholder")

    def test_detect_mime(self):
        self.assertEqual(image_ai._detect_mime(make_solid_png()), "image/png")
        self.assertEqual(image_ai._detect_mime(make_noise_jpeg()), "image/jpeg")


class BlacklistTests(TestCase):
    def test_exact_domain(self):
        self.assertTrue(image_ai.is_blacklisted("https://carsales.com.au/img/1.jpg"))

    def test_subdomain(self):
        self.assertTrue(
            image_ai.is_blacklisted("https://cdn.images.carsales.com.au/img/1.jpg")
        )

    def test_parent_domain_url_with_path(self):
        self.assertTrue(
            image_ai.is_blacklisted("https://www.redbook.com.au/cars/news/photo.png")
        )

    def test_all_blacklisted_domains(self):
        for domain in image_ai.BLACKLISTED_DOMAINS:
            self.assertTrue(image_ai.is_blacklisted(f"https://{domain}/x.jpg"), domain)

    def test_non_blacklisted(self):
        self.assertFalse(
            image_ai.is_blacklisted("https://upload.wikimedia.org/wikipedia/commons/x.jpg")
        )
        self.assertFalse(image_ai.is_blacklisted("https://carsales.com.evil.ru/x.jpg"))

    def test_empty(self):
        self.assertFalse(image_ai.is_blacklisted(""))
        self.assertFalse(image_ai.is_blacklisted(None))


class ClassifyCommandTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="carreb-classify-media-")
        self.out_dir = os.path.join(self.media_root, "vehicle_images")
        os.makedirs(self.out_dir, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self._override = override_settings(MEDIA_ROOT=self.media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)

    def _write_image(self, name, data):
        path = os.path.join(self.out_dir, name)
        with open(path, "wb") as f:
            f.write(data)
        return settings.MEDIA_URL + "vehicle_images/" + name

    def test_bad_ai_verdict_clears_url_and_deletes_file(self):
        url = self._write_image("bad1.jpg", make_noise_jpeg())
        vehicle = make_vehicle(image_url=url)

        with mock.patch(
            "apps.vehicles.services.image_ai.classify_image",
            return_value={"verdict": "silhouette", "reason": "flat shape",
                          "raw_verdict": "silhouette"},
        ) as ai_mock:
            call_command("classify_vehicle_images")

        vehicle.refresh_from_db()
        self.assertIsNone(vehicle.image_url)
        self.assertEqual(vehicle.image_classification["verdict"], "silhouette")
        self.assertEqual(vehicle.image_classification["source"], "grok")
        self.assertFalse(os.path.exists(os.path.join(self.out_dir, "bad1.jpg")))
        ai_mock.assert_called_once()

    def test_real_photo_verdict_keeps_everything(self):
        url = self._write_image("good1.jpg", make_noise_jpeg())
        vehicle = make_vehicle(image_url=url)

        with mock.patch(
            "apps.vehicles.services.image_ai.classify_image",
            return_value={"verdict": "real_photo", "reason": "genuine photo",
                          "raw_verdict": "real_photo"},
        ):
            call_command("classify_vehicle_images")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.image_url, url)
        self.assertEqual(vehicle.image_classification["verdict"], "real_photo")
        self.assertTrue(os.path.exists(os.path.join(self.out_dir, "good1.jpg")))

    def test_heuristic_verdict_skips_ai_and_deletes(self):
        url = self._write_image("solid1.png", make_solid_png())
        vehicle = make_vehicle(image_url=url)

        with mock.patch(
            "apps.vehicles.services.image_ai.classify_image"
        ) as ai_mock:
            call_command("classify_vehicle_images")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.image_classification["source"], "heuristic")
        self.assertEqual(vehicle.image_classification["verdict"], "silhouette")
        self.assertIsNone(vehicle.image_url)
        self.assertFalse(os.path.exists(os.path.join(self.out_dir, "solid1.png")))
        ai_mock.assert_not_called()

    def test_dry_run_changes_nothing(self):
        url = self._write_image("dry1.jpg", make_noise_jpeg())
        vehicle = make_vehicle(image_url=url)

        with mock.patch(
            "apps.vehicles.services.image_ai.classify_image",
            return_value={"verdict": "placeholder", "reason": "empty",
                          "raw_verdict": "placeholder_empty"},
        ):
            call_command("classify_vehicle_images", "--dry-run")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.image_url, url)
        self.assertIsNone(vehicle.image_classification)
        self.assertTrue(os.path.exists(os.path.join(self.out_dir, "dry1.jpg")))

    def test_file_shared_with_other_vehicle_is_not_deleted(self):
        url = self._write_image("shared1.jpg", make_noise_jpeg())
        v1 = make_vehicle(brand="MakeA", image_url=url)
        v2 = make_vehicle(brand="MakeB", image_url=url)

        with mock.patch(
            "apps.vehicles.services.image_ai.classify_image",
            return_value={"verdict": "placeholder", "reason": "empty",
                          "raw_verdict": "placeholder_empty"},
        ):
            call_command("classify_vehicle_images", "--limit", "1")

        v1.refresh_from_db()
        v2.refresh_from_db()
        self.assertIsNone(v1.image_url)
        self.assertEqual(v2.image_url, url)  # other vehicle untouched
        self.assertTrue(os.path.exists(os.path.join(self.out_dir, "shared1.jpg")))

    def test_missing_file_counts_and_warns(self):
        vehicle = make_vehicle(image_url=settings.MEDIA_URL + "vehicle_images/nope.jpg")

        with mock.patch(
            "apps.vehicles.services.image_ai.classify_image"
        ) as ai_mock:
            call_command("classify_vehicle_images")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.image_classification["source"], "none")
        self.assertIn("missing file", vehicle.image_classification["detail"])
        ai_mock.assert_not_called()

    def test_external_url_is_skipped(self):
        vehicle = make_vehicle(image_url="https://example.com/car.jpg")

        with mock.patch(
            "apps.vehicles.services.image_ai.classify_image"
        ) as ai_mock:
            call_command("classify_vehicle_images")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.image_url, "https://example.com/car.jpg")
        ai_mock.assert_not_called()

    def test_no_ai_flag_never_calls_ai(self):
        url = self._write_image("noai1.jpg", make_noise_jpeg())
        vehicle = make_vehicle(image_url=url)

        with mock.patch(
            "apps.vehicles.services.image_ai.classify_image"
        ) as ai_mock:
            call_command("classify_vehicle_images", "--no-ai")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.image_classification["verdict"], "unclassified")
        self.assertEqual(vehicle.image_url, url)  # inconclusive + no-ai => kept
        ai_mock.assert_not_called()


class CleanupOrphanImagesTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="carreb-cleanup-media-")
        self.out_dir = os.path.join(self.media_root, "vehicle_images")
        os.makedirs(self.out_dir, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self._override = override_settings(MEDIA_ROOT=self.media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)

    def _write(self, name, data=b"x" * 100):
        path = os.path.join(self.out_dir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_removes_only_unreferenced_files(self):
        ref_path = self._write("referenced.jpg")
        orphan_path = self._write("orphan.jpg")
        make_vehicle(image_url=settings.MEDIA_URL + "vehicle_images/referenced.jpg")

        call_command("cleanup_orphan_images")

        self.assertTrue(os.path.exists(ref_path))
        self.assertFalse(os.path.exists(orphan_path))

    def test_dry_run_removes_nothing(self):
        orphan_path = self._write("orphan2.jpg")

        call_command("cleanup_orphan_images", "--dry-run")

        self.assertTrue(os.path.exists(orphan_path))

    def test_refuses_path_outside_media_root(self):
        self._write("keep.jpg")
        outside = tempfile.mkdtemp(prefix="carreb-outside-")
        self.addCleanup(shutil.rmtree, outside, True)

        call_command("cleanup_orphan_images", "--path", outside)

        self.assertTrue(os.path.exists(os.path.join(self.out_dir, "keep.jpg")))


class ScrapeVehicleImagesTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="carreb-scrape-media-")
        os.makedirs(os.path.join(self.media_root, "vehicle_images"), exist_ok=True)
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self._override = override_settings(MEDIA_ROOT=self.media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)

    def test_blacklisted_candidate_is_skipped(self):
        make_vehicle(brand="SkipMe")
        with mock.patch(
            "apps.vehicles.services.image_ai.find_commons_image",
            return_value="https://img.carsales.com.au/photos/cars.jpg",
        ), mock.patch(
            "apps.vehicles.services.image_ai.download_image"
        ) as dl_mock:
            call_command("scrape_vehicle_images")

        dl_mock.assert_not_called()
        self.assertEqual(Vehicle.objects.get(brand="SkipMe").image_url, None)

    def test_good_candidate_is_saved(self):
        vehicle = make_vehicle(brand="GoodMake")
        good_bytes = make_noise_jpeg()
        out_dir = os.path.join(self.media_root, "vehicle_images")

        def fake_download(url, out, headers=None, delay=0.0, log=None):
            path = os.path.join(out, "newimg.jpg")
            with open(path, "wb") as f:
                f.write(good_bytes)
            return path

        with mock.patch(
            "apps.vehicles.services.image_ai.find_commons_image",
            return_value="https://upload.wikimedia.org/wikipedia/commons/newimg.jpg",
        ), mock.patch(
            "apps.vehicles.services.image_ai.download_image",
            side_effect=fake_download,
        ):
            call_command("scrape_vehicle_images")

        vehicle.refresh_from_db()
        self.assertEqual(
            vehicle.image_url, settings.MEDIA_URL + "vehicle_images/newimg.jpg"
        )
        self.assertTrue(os.path.exists(os.path.join(out_dir, "newimg.jpg")))

    def test_rejected_candidate_is_not_saved(self):
        vehicle = make_vehicle(brand="BadMake")
        bad_bytes = make_solid_png()
        out_dir = os.path.join(self.media_root, "vehicle_images")

        def fake_download(url, out, headers=None, delay=0.0, log=None):
            path = os.path.join(out, "badimg.png")
            with open(path, "wb") as f:
                f.write(bad_bytes)
            return path

        with mock.patch(
            "apps.vehicles.services.image_ai.find_commons_image",
            return_value="https://upload.wikimedia.org/wikipedia/commons/badimg.png",
        ), mock.patch(
            "apps.vehicles.services.image_ai.download_image",
            side_effect=fake_download,
        ):
            call_command("scrape_vehicle_images")

        vehicle.refresh_from_db()
        self.assertIsNone(vehicle.image_url)
        self.assertFalse(os.path.exists(os.path.join(out_dir, "badimg.png")))

    def test_dry_run_does_not_download(self):
        make_vehicle()
        with mock.patch(
            "apps.vehicles.services.image_ai.find_commons_image",
            return_value="https://upload.wikimedia.org/wikipedia/commons/x.jpg",
        ), mock.patch(
            "apps.vehicles.services.image_ai.download_image"
        ) as dl_mock:
            call_command("scrape_vehicle_images", "--dry-run")

        dl_mock.assert_not_called()
        self.assertIsNone(Vehicle.objects.first().image_url)
