"""Copy FCAI silhouette images from docs/ into MEDIA_ROOT/vehicle_silhouettes.

Usage:
    python manage.py collect_vehicle_silhouettes
    python manage.py collect_vehicle_silhouettes --source /path/to/silhouettes
"""
import os

from django.core.management.base import BaseCommand
from django.conf import settings

from apps.vehicles.services.silhouette_lookup import collect_silhouettes


class Command(BaseCommand):
    help = "Copy FCAI vehicle silhouette images into MEDIA_ROOT/vehicle_silhouettes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            default="",
            help="Optional source directory (defaults to the docs/Tier 3 Images folder)",
        )

    def handle(self, *args, **options):
        source = options.get("source") or os.path.join(
            settings.BASE_DIR,
            "docs",
            "Tier 3 Images - FCAI Vehicle Silhouette Images NEW CARS",
        )

        self.stdout.write(f"Collecting silhouettes from: {source}")
        copied = collect_silhouettes(source_dir=source)

        if not copied:
            self.stdout.write(self.style.WARNING("No .png files found."))
            return

        self.stdout.write(self.style.SUCCESS(f"Copied {len(copied)} silhouette images:"))
        for name in sorted(copied):
            self.stdout.write(f"  {name}")
