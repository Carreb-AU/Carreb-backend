"""Warm the 30-day AI estimate caches (spec sheet / ANCAP / engine).

One-time backfill and manual top-up for GVG/AI rows whose cards show null
spec fields. The same warmer runs nightly via the sweep task and on-sight
via fire-and-forget tasks from search endpoints.

Usage:
    python manage.py warm_vehicle_estimates --source ai
    python manage.py warm_vehicle_estimates --source gvg --limit 500 --workers 8
"""
import logging

from django.core.management.base import BaseCommand

from apps.vehicles.services.vehicle_card import warm_cold_records

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Warm AI estimate caches for GVG/AI vehicle records."

    def add_arguments(self, parser):
        parser.add_argument('--source', choices=['ai', 'gvg'], default='ai')
        parser.add_argument('--limit', type=int, default=500,
                            help='max records to warm this run')
        parser.add_argument('--offset', type=int, default=0)
        parser.add_argument('--workers', type=int, default=4)

    def handle(self, *args, **options):
        result = warm_cold_records(
            options['source'], limit=options['limit'],
            offset=options['offset'], workers=options['workers'])
        self.stdout.write(self.style.SUCCESS(
            f"{options['source']}: warmed {result['warmed']}, "
            f"already warm {result['already_warm']} "
            f"(table total {result['total']}, "
            f"next offset {result['next_offset']}, "
            f"remaining {result['remaining']})"))
