import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.vehicles.models import Vehicle
from apps.vehicles.services import image_ai

REQUEST_DELAY_SECONDS = 0.5


class Command(BaseCommand):
    help = (
        "Scrape replacement images for vehicles lacking image_url from allowlisted "
        "sources only (Wikimedia Commons). Candidates on blacklisted domains are "
        "skipped before download. Candidates are validated with heuristics, plus "
        "Grok vision when --ai is given. "
        "TODO: press-portal (OEM media kit) support is out of scope for now."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0,
                            help="Only process N vehicles")
        parser.add_argument("--dry-run", action="store_true",
                            help="Find and report candidates only; no download/save")
        parser.add_argument("--ai", action="store_true",
                            help="Validate candidates with Grok vision (requires xAI credits)")
        parser.add_argument("--commons-only", action="store_true",
                            help="Only use Wikimedia Commons (currently the only source)")

    def handle(self, *args, **options):
        limit = options["limit"]
        dry_run = options["dry_run"]
        use_ai = options["ai"]
        _ = options["commons_only"]  # Commons is currently the only allowlisted source.

        qs = (
            Vehicle.objects.filter(image_url__isnull=True)
            | Vehicle.objects.filter(image_url="")
        ).order_by("brand", "model")
        if limit:
            qs = qs[:limit]

        out_dir = os.path.join(str(settings.MEDIA_ROOT), "vehicle_images")
        if not dry_run:
            os.makedirs(out_dir, exist_ok=True)

        headers = dict(image_ai.BROWSER_HEADERS)

        scraped = 0
        skipped = 0
        reasons = {}

        def skip(reason):
            nonlocal skipped
            skipped += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            self.stderr.write(self.style.WARNING(f"skipped: {reason}"))

        for vehicle in qs:
            query = f"{vehicle.brand} {vehicle.model}"
            candidate = image_ai.find_commons_image(
                query, headers, REQUEST_DELAY_SECONDS, log=self
            )
            if not candidate:
                skip("no candidate")
                continue

            # Enforce the domain blacklist BEFORE any download.
            if image_ai.is_blacklisted(candidate):
                skip("blacklisted domain")
                continue

            if dry_run:
                self.stdout.write(f"Would fetch for {query}: {candidate}")
                scraped += 1
                continue

            local_path = image_ai.download_image(
                candidate, out_dir, headers, REQUEST_DELAY_SECONDS, log=self
            )
            if not local_path:
                skip("download failed")
                continue

            try:
                with open(local_path, "rb") as f:
                    image_bytes = f.read()
            except OSError as e:
                skip("read failed")
                self.stderr.write(f"WARN could not read {local_path}: {e}")
                continue

            # Validate: heuristics first, then (optionally) Grok vision.
            verdict = None
            detail = ""
            h = image_ai.heuristic_check(image_bytes)
            if h:
                verdict, detail = h["verdict"], h["detail"]
            elif use_ai:
                time.sleep(0.4)
                try:
                    result = image_ai.classify_image(image_bytes)
                    verdict = None if result["verdict"] == "real_photo" else result["verdict"]
                    detail = result.get("reason", "")
                except image_ai.ImageAIError as e:
                    verdict = "unclassified"
                    detail = str(e)

            if verdict:
                try:
                    os.remove(local_path)
                except OSError:
                    pass
                skip(f"rejected ({verdict}: {detail})")
                continue

            relative_url = settings.MEDIA_URL + "vehicle_images/" + os.path.basename(local_path)
            vehicle.image_url = relative_url
            vehicle.save(update_fields=["image_url"])
            scraped += 1
            self.stdout.write(self.style.SUCCESS(f"OK {query} -> {relative_url}"))

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Scraped {scraped} image(s), skipped {skipped}."
            )
        )
        for reason in sorted(reasons):
            self.stdout.write(f"  {reason:<25} {reasons[reason]}")
