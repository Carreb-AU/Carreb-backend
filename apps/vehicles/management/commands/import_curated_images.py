import csv
import os
import shutil
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.vehicles.models import ManualVehicleEnrichment, Vehicle, VehicleIdentity

MEDIA_URL_PREFIX = "/media/vehicle_images/"
CURATED_CLASSIFICATION = {"verdict": "real_photo", "source": "curated-import"}

SILHOUETTES = (
    (("hatch", "hatchback"), "silhouette-hatch.png"),
    (("suv", "crossover"), "silhouette-suv.png"),
    (("ute", "pickup", "cab chassis", "dual cab", "single cab", "crew cab"),
     "silhouette-ute.png"),
    (("van", "cargo"), "silhouette-van.png"),
    (("people-mover", "people mover", "minivan", "mpv"), "silhouette-people-mover.png"),
    (("sedan", "coupe", "convertible", "wagon", "gran coupe", "touring", "liftback"),
     "silhouette-sedan.png"),
)


def silhouette_for(body_style):
    text = (body_style or "").casefold()
    for needles, filename in SILHOUETTES:
        if any(n in text for n in needles):
            return filename
    return None


class Command(BaseCommand):
    help = (
        "Import the curated hero-image set (one 1752x1000 PNG per model-year, scraped "
        "from manufacturer/press sites) and retire all locally stored vehicle images. "
        "Matches manifest rows to vehicles by make+model+year (nearest-year fallback "
        "within a model line), fills unmatched vehicles with body-type silhouettes, "
        "and deletes old image files no longer referenced by any table. See "
        "IMPORT_NOTE_Meenam.md in the curated set."
    )

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True,
                            help="Path to image_manifest.csv from the curated set")
        parser.add_argument("--images-dir", required=True,
                            help="Directory containing the curated PNGs")
        parser.add_argument("--silhouettes-dir", default="",
                            help="Directory containing silhouette-*.png (enables silhouette fill)")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report matches/wipe plan only; change nothing")
        parser.add_argument("--no-wipe", action="store_true",
                            help="Keep existing local images instead of deleting them")

    def handle(self, *args, **options):
        manifest_path = options["manifest"]
        images_dir = options["images_dir"]
        sil_dir = options["silhouettes_dir"]
        dry_run = options["dry_run"]
        wipe = not options["no_wipe"]

        rows = self._load_manifest(manifest_path)
        if not rows:
            self.stderr.write(self.style.ERROR("No usable manifest rows; aborting."))
            return

        missing_files = [r["image_file"] for r in rows
                         if not os.path.isfile(os.path.join(images_dir, r["image_file"]))]
        if missing_files:
            self.stderr.write(self.style.ERROR(
                f"{len(missing_files)} manifest images missing from {images_dir} "
                f"(e.g. {missing_files[:3]}); aborting."
            ))
            return

        if dry_run:
            self.stdout.write(f"[dry-run] manifest rows: {len(rows)}")

        if wipe:
            self._wipe_old_images(dry_run=dry_run)

        stats = self._apply(rows, images_dir, dry_run=dry_run)

        sil_stats = {"filled": 0, "needs_image": 0}
        if sil_dir:
            sil_stats = self._fill_silhouettes(sil_dir, dry_run=dry_run)

        self.stdout.write(self.style.SUCCESS(
            f"Curated rows: {len(rows)} | vehicles updated: {stats['vehicles_updated']} "
            f"({stats['bulk_updates']} model-year rows matched) | "
            f"silhouettes filled: {sil_stats['filled']} | needs image: {sil_stats['needs_image']}"
        ))

    # ------------------------------------------------------------------
    def _load_manifest(self, path):
        rows = []
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if (row.get("status") or "").strip().upper() == "RETIRED":
                    continue
                try:
                    year = int(float(row["year"]))
                except (KeyError, TypeError, ValueError):
                    continue
                rows.append({
                    "image_file": (row.get("image_file") or "").strip(),
                    "make": (row.get("make") or "").strip(),
                    "model": (row.get("model") or "").strip(),
                    "year": year,
                })
        return [r for r in rows if r["image_file"] and r["make"] and r["model"]]

    def _local_basename(self, url):
        if not url or not url.startswith("/"):
            return None
        return os.path.basename(urlparse(url).path or "")

    def _wipe_old_images(self, dry_run):
        """Delete local vehicle-image files and clear image_url on Vehicle/VehicleIdentity."""
        media_root = os.path.realpath(str(settings.MEDIA_ROOT))
        target = os.path.realpath(os.path.join(media_root, "vehicle_images"))
        if not (target == media_root or target.startswith(media_root + os.sep)):
            self.stderr.write(self.style.ERROR(
                f"Refusing to wipe: {target} is outside MEDIA_ROOT ({media_root})"))
            return

        # Files referenced by manual overrides are never deleted.
        protected = set()
        for url in ManualVehicleEnrichment.objects.exclude(
                image_url__isnull=True).exclude(image_url="").values_list("image_url", flat=True):
            name = self._local_basename(url)
            if name:
                protected.add(name)

        referenced = {"Vehicle": {}, "VehicleIdentity": {}}
        for label, model in (("Vehicle", Vehicle), ("VehicleIdentity", VehicleIdentity)):
            for url in model.objects.exclude(image_url__isnull=True).exclude(
                    image_url="").values_list("image_url", flat=True):
                name = self._local_basename(url)
                if name:
                    referenced[label][name] = referenced[label].get(name, 0) + 1

        deleted = 0
        if os.path.isdir(target):
            for name in sorted(os.listdir(target)):
                path = os.path.join(target, name)
                if not os.path.isfile(path) or name in protected:
                    continue
                if dry_run:
                    self.stdout.write(f"[dry-run] would delete old file {name}")
                    deleted += 1
                    continue
                try:
                    os.remove(path)
                    deleted += 1
                except OSError as e:
                    self.stderr.write(f"WARN could not delete {path}: {e}")

        cleared = {}
        if not dry_run:
            with transaction.atomic():
                for label, model in (("Vehicle", Vehicle),
                                     ("VehicleIdentity", VehicleIdentity)):
                    n = 0
                    for url in list(model.objects.exclude(image_url__isnull=True).exclude(
                            image_url="").values_list("image_url", flat=True)):
                        if self._local_basename(url):
                            n += model.objects.filter(image_url=url).update(image_url=None)
                    cleared[label] = n
        self.stdout.write(
            f"[wipe] {'would delete' if dry_run else 'deleted'} {deleted} old file(s); "
            f"cleared URLs: {cleared or '(dry-run)'}"
        )

    # ------------------------------------------------------------------
    def _apply(self, rows, images_dir, dry_run):
        media_root = os.path.realpath(str(settings.MEDIA_ROOT))
        target_dir = os.path.realpath(os.path.join(media_root, "vehicle_images"))
        if not (target_dir == media_root or target_dir.startswith(media_root + os.sep)):
            self.stderr.write(self.style.ERROR(
                f"Refusing to copy into {target_dir}: outside MEDIA_ROOT"))
            return {"vehicles_updated": 0, "bulk_updates": 0}

        # Group by normalised make+model -> {year: image_file}
        by_model = {}
        for r in rows:
            key = (r["make"].casefold(), r["model"].casefold())
            by_model.setdefault(key, {})[r["year"]] = r["image_file"]

        if not dry_run:
            os.makedirs(target_dir, exist_ok=True)
            copied = set()
            for r in rows:
                if r["image_file"] in copied:
                    continue
                shutil.copy2(os.path.join(images_dir, r["image_file"]),
                             os.path.join(target_dir, r["image_file"]))
                copied.add(r["image_file"])

        vehicles_updated = 0
        bulk_updates = 0
        unmatched_rows = []
        for (make, model), year_map in sorted(by_model.items()):
            vehicles = Vehicle.objects.filter(brand__iexact=make, model__iexact=model)
            if not vehicles.exists():
                unmatched_rows.append(f"{make} {model} ({len(year_map)} yr)")
                continue
            bulk_updates += 1
            years = sorted(year_map)
            for v in vehicles:
                image_file = year_map.get(v.year)
                if image_file is None:
                    nearest = min(years, key=lambda y: abs(y - v.year))
                    if abs(nearest - v.year) > 1:
                        continue
                    image_file = year_map[nearest]
                if not dry_run:
                    v.image_url = f"{MEDIA_URL_PREFIX}{image_file}"
                    v.image_classification = dict(CURATED_CLASSIFICATION)
                    v.save(update_fields=["image_url", "image_classification"])
                vehicles_updated += 1

        if unmatched_rows:
            self.stdout.write(self.style.WARNING(
                "Manifest models not found in catalogue:\n  " + "\n  ".join(unmatched_rows)))
        return {"vehicles_updated": vehicles_updated, "bulk_updates": bulk_updates}

    # ------------------------------------------------------------------
    def _fill_silhouettes(self, sil_dir, dry_run):
        media_root = os.path.realpath(str(settings.MEDIA_ROOT))
        target_dir = os.path.realpath(os.path.join(media_root, "vehicle_images"))
        available = {name for name in os.listdir(sil_dir)
                     if name.startswith("silhouette-") and name.endswith(".png")}

        filled = 0
        needs_image = 0
        to_update = []
        for v in Vehicle.objects.filter(image_url__isnull=True):
            filename = silhouette_for(v.body_style)
            if filename and filename in available:
                to_update.append((v, filename))
            else:
                needs_image += 1
                self.stdout.write(self.style.WARNING(
                    f"needs image: {v.brand} {v.model} {v.year} ({v.body_style or 'no body_style'})"))

        if not dry_run:
            os.makedirs(target_dir, exist_ok=True)
            for filename in {f for _, f in to_update}:
                shutil.copy2(os.path.join(sil_dir, filename),
                             os.path.join(target_dir, filename))
            for v, filename in to_update:
                v.image_url = f"{MEDIA_URL_PREFIX}{filename}"
                v.image_classification = {"verdict": "silhouette", "source": "curated-import"}
                v.save(update_fields=["image_url", "image_classification"])
        filled = len(to_update)

        return {"filled": filled, "needs_image": needs_image}
