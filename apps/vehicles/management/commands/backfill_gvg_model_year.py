"""Backfill VehicleIdentity.model_year and search_text from raw_data.

B-01: GVG rows imported before the model_year column existed carry the MY
label (e.g. "MY25") only inside raw_data['ModelReleaseVersion'], and their
search_text lacks the MY-derived year — so "zeekr 009 2025" finds nothing.
This command populates model_year and rebuilds search_text without a full
re-import (stable UUIDs and FKs untouched).

Run on the server:
    docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T web \
        python manage.py backfill_gvg_model_year
"""
from django.core.management.base import BaseCommand

from apps.vehicles.models import VehicleIdentity
from apps.vehicles.services.gvg_import import identity_search_text


class Command(BaseCommand):
    help = "Populate model_year and rebuild search_text for GVG identity rows from raw_data."

    def handle(self, *args, **options):
        updated = 0
        for rec in VehicleIdentity.objects.all().iterator(chunk_size=500):
            label = (rec.raw_data or {}).get('ModelReleaseVersion') or ''
            label = str(label).strip()[:50]
            new_text = identity_search_text(
                rec.year, rec.make, rec.model, rec.variant, label)
            if label == rec.model_year and new_text == rec.search_text:
                continue
            rec.model_year = label
            rec.search_text = new_text
            rec.save(update_fields=['model_year', 'search_text'])
            updated += 1
        self.stdout.write(self.style.SUCCESS(
            f"Backfilled model_year/search_text on {updated} GVG rows."))
