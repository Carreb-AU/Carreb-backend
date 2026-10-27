import os
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.vehicles.models import Vehicle
from apps.vehicles.services import image_ai

AI_DELAY_SECONDS = 0.4

# Verdicts considered bad enough to clear image_url + delete the file.
# "unclassified" (AI failure / heuristics inconclusive) keeps the image in place.
BAD_VERDICTS = {"silhouette", "illustration", "logo", "placeholder", "suspect"}


def local_path_for_image_url(image_url: str):
    """Map a Vehicle.image_url to a path relative to MEDIA_ROOT, or None if external."""
    if not image_url:
        return None
    parsed = urlparse(image_url)
    if parsed.scheme and parsed.scheme != "file":
        return None  # external URL — no local file
    path = parsed.path if parsed.scheme else image_url
    media_url = getattr(settings, "MEDIA_URL", "/media/")
    if path.startswith(media_url):
        rel = path[len(media_url):]
    else:
        rel = path.lstrip("/")
    return rel


class Command(BaseCommand):
    help = (
        "Classify existing Vehicle.image_url images as real photos vs silhouettes/"
        "placeholders using heuristics and (optionally) Grok vision. In a real run, "
        "vehicles whose final verdict is not real_photo get image_url cleared and the "
        "local media file deleted (unless still referenced by another vehicle)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Classify and report only; change nothing")
        parser.add_argument("--limit", type=int, default=0,
                            help="Only process N vehicles")
        parser.add_argument("--offset", type=int, default=0,
                            help="Skip the first N vehicles")
        parser.add_argument("--only-uncleared", action="store_true",
                            help="Only process vehicles whose image_url is still set")
        parser.add_argument("--no-ai", action="store_true",
                            help="Heuristics only; skip Grok vision")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        no_ai = options["no_ai"]

        qs = (
            Vehicle.objects.exclude(image_url__isnull=True)
            .exclude(image_url="")
            .order_by("brand", "model")
        )
        if options["offset"]:
            qs = qs[options["offset"]:]
        if options["limit"]:
            qs = qs[: options["limit"]]

        media_root = str(getattr(settings, "MEDIA_ROOT", "") or "")
        if not media_root:
            self.stderr.write("MEDIA_ROOT is not set; nothing to do.")
            return

        counts = {}
        bytes_freed = 0
        files_deleted = 0
        missing_file = 0
        to_save = []

        for vehicle in qs:
            original_url = vehicle.image_url
            rel = local_path_for_image_url(original_url)
            counts["_seen"] = counts.get("_seen", 0) + 1
            entry = {"verdict": "unclassified", "source": "none", "detail": "", "at": ""}

            image_bytes = None
            full_path = None
            if rel is None:
                missing_file += 1
                counts["missing_file"] = counts.get("missing_file", 0) + 1
                self.stderr.write(
                    f"WARN {vehicle}: image_url is external ({original_url}); skipping file"
                )
                entry["detail"] = "external image_url"
            else:
                full_path = os.path.join(media_root, rel)
                try:
                    with open(full_path, "rb") as f:
                        image_bytes = f.read()
                except OSError as e:
                    missing_file += 1
                    counts["missing_file"] = counts.get("missing_file", 0) + 1
                    self.stderr.write(f"WARN {vehicle}: cannot read {full_path}: {e}")
                    entry["detail"] = f"missing file: {rel}"

            if image_bytes is not None:
                # 1. Heuristic pre-screen.
                h = image_ai.heuristic_check(image_bytes)
                if h:
                    entry.update(verdict=h["verdict"], source="heuristic", detail=h["detail"])
                elif no_ai:
                    entry.update(verdict="unclassified", source="heuristic",
                                 detail="heuristics inconclusive; --no-ai set")
                else:
                    # 2. Grok vision.
                    time.sleep(AI_DELAY_SECONDS)
                    try:
                        result = image_ai.classify_image(image_bytes)
                        entry.update(verdict=result["verdict"], source="grok",
                                     detail=result.get("reason", ""))
                    except image_ai.ImageAIError as e:
                        entry.update(verdict="unclassified", source="grok", detail=str(e))

            entry["at"] = datetime.now(timezone.utc).isoformat()
            vehicle.image_classification = entry
            counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1
            to_save.append(vehicle)

            # 3. Act on bad verdicts (real run only).
            if (
                not dry_run
                and image_bytes is not None
                and entry["verdict"] in BAD_VERDICTS
            ):
                vehicle.image_url = None
                other_refs = Vehicle.objects.filter(
                    image_url=original_url
                ).exclude(pk=vehicle.pk).exists()
                if other_refs:
                    self.stderr.write(
                        f"NOTE {full_path} still referenced by another vehicle; file kept"
                    )
                else:
                    try:
                        size = os.path.getsize(full_path)
                        os.remove(full_path)
                        files_deleted += 1
                        bytes_freed += size
                    except OSError as e:
                        self.stderr.write(f"WARN could not delete {full_path}: {e}")

        if not dry_run:
            for vehicle in to_save:
                vehicle.save(update_fields=["image_classification", "image_url"])
        else:
            self.stdout.write(self.style.WARNING("Dry run: no changes were made."))

        self.stdout.write("")
        self.stdout.write("Classification summary:")
        for verdict in sorted(counts):
            if verdict == "_seen":
                continue
            self.stdout.write(f"  {verdict:<15} {counts[verdict]}")
        self.stdout.write(f"  {'total seen':<15} {counts.get('_seen', 0)}")
        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {files_deleted} file(s), freed {bytes_freed} bytes "
                    f"({bytes_freed / (1024 * 1024):.1f} MiB)."
                )
            )
