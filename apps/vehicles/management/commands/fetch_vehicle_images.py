import os
import time
import uuid
from urllib.parse import unquote

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from apps.vehicles.models import Vehicle


WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "CarrebBot/1.0 (carreb.com.au; dev@carreb.com.au)"


class Command(BaseCommand):
    help = (
        "Fetch vehicle images from Wikimedia Commons for vehicles missing image_url. "
        "By default, freely licensed images are downloaded to MEDIA_ROOT/vehicle_images. "
        "Use --no-download to store the Commons URL directly instead (no disk usage). "
        "Vehicles with no match keep their current image_url (use set_vehicle_fallback_images "
        "afterwards if you want a placeholder for the rest)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--delay",
            type=float,
            default=0.25,
            help="Seconds to sleep between API calls (default 0.25)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Only process N vehicles (useful for testing)",
        )
        parser.add_argument(
            "--fallback-url",
            type=str,
            default="",
            help="If no Commons image is found, set this URL",
        )
        parser.add_argument(
            "--no-download",
            action="store_true",
            help="Store the Wikimedia Commons URL directly in image_url without downloading the file (no disk usage)",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            default="",
            help="Optional host to prepend to MEDIA_URL, e.g. https://api.carreb.com.au",
        )
        parser.add_argument(
            "--replace-existing",
            type=str,
            default="",
            help="Re-fetch images for vehicles whose current image_url matches this value",
        )

    def handle(self, *args, **options):
        delay = options["delay"]
        limit = options["limit"]
        fallback_url = options["fallback_url"]
        base_url = options["base_url"].rstrip("/")
        replace_existing = options["replace_existing"]
        no_download = options["no_download"]

        qs = Vehicle.objects.filter(image_url__isnull=True) | Vehicle.objects.filter(
            image_url=""
        )
        if replace_existing:
            qs = qs | Vehicle.objects.filter(image_url=replace_existing)
        if limit:
            qs = qs[:limit]

        total = qs.count()
        found = 0
        missing = 0

        out_dir = os.path.join(settings.MEDIA_ROOT, "vehicle_images")
        os.makedirs(out_dir, exist_ok=True)

        headers = {"User-Agent": USER_AGENT}

        for vehicle in qs:
            query = f"{vehicle.brand} {vehicle.model}"
            self.stdout.write(f"Searching: {query} … ", ending="")

            time.sleep(delay)
            image_url = self._find_commons_image(query, headers, delay)

            if image_url:
                if no_download:
                    vehicle.image_url = image_url
                    vehicle.save(update_fields=["image_url"])
                    found += 1
                    self.stdout.write(self.style.SUCCESS("OK (link only)"))
                    continue
                local_path = self._download_image(image_url, out_dir, headers, delay)
                if local_path:
                    relative_url = settings.MEDIA_URL + "vehicle_images/" + os.path.basename(local_path)
                    vehicle.image_url = (base_url + relative_url) if base_url else relative_url
                    vehicle.save(update_fields=["image_url"])
                    found += 1
                    self.stdout.write(self.style.SUCCESS("OK"))
                else:
                    missing += 1
                    self.stdout.write(self.style.WARNING("download failed"))
            else:
                missing += 1
                self.stdout.write(self.style.WARNING("not found"))

        if fallback_url:
            remaining = (
                Vehicle.objects.filter(image_url__isnull=True)
                | Vehicle.objects.filter(image_url="")
            ).count()
            if remaining:
                updated = (
                    Vehicle.objects.filter(image_url__isnull=True)
                    | Vehicle.objects.filter(image_url="")
                ).update(image_url=fallback_url)
                self.stdout.write(
                    self.style.SUCCESS(f"Applied fallback URL to {updated} vehicles")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {total} vehicles: {found} images downloaded, {missing} missing"
            )
        )

    def _find_commons_image(self, query: str, headers: dict, delay: float) -> str:
        """Return the URL of the first Wikimedia Commons image matching the query, or ''."""
        time.sleep(delay)
        search_params = {
            "action": "query",
            "generator": "search",
            "gsrnamespace": 6,
            "gsrsearch": query,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "format": "json",
            "origin": "*",
        }
        try:
            r = requests.get(WIKIMEDIA_API, params=search_params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            self.stderr.write(f"Commons search error: {e}")
            return ""

        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return ""

        # Pick the first result that has a URL and is actually an image file.
        for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
            imageinfo = page.get("imageinfo")
            if not imageinfo:
                continue
            url = imageinfo[0].get("url")
            if url:
                return url
        return ""

    def _download_image(self, url: str, out_dir: str, headers: dict, delay: float) -> str:
        """Download image to out_dir, return local file path or ''."""
        ext = os.path.splitext(unquote(url).split("?")[0])[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            ext = ".jpg"

        filename = f"{uuid.uuid4().hex}{ext}"
        local_path = os.path.join(out_dir, filename)

        # Strip tracking query params before downloading; they cause 429s on upload.wikimedia.org.
        download_url = url.split("?")[0]

        time.sleep(delay)
        try:
            r = requests.get(download_url, headers=headers, timeout=30)
            r.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(r.content)
            return local_path
        except Exception as e:
            self.stderr.write(f"Download error: {e}")
            return ""
