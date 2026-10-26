"""Build the CORE Dial rows from a "Consolidated Vehicles v6.4" workbook.

Usage:
    python manage.py build_core_dial --path "02 Vehicles & CORE - 13-Oct-26.xlsx"
    python manage.py build_core_dial --path <workbook> --scoring-version v6.4-rebatch-07Oct26 --as-at 2026-10-07
    python manage.py build_core_dial --path <workbook> --dry-run

Creates a new CoreDialBatch (marked current; all other batches are demoted)
and one CoreDialRow per on-sale, unsuppressed listing per state, cut to the
Mode B row. Suppressed listings (is_suppressed in 21-Oct+ workbooks) are
counted and skipped.
"""
import logging
import os
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.vehicles.models import CoreDialBatch, CoreDialRow, Vehicle
from apps.vehicles.services.core_dial_import import parse_workbook

logger = logging.getLogger(__name__)

DEFAULT_WORKBOOK = '02 Vehicles & CORE - 13-Oct-26.xlsx'


class Command(BaseCommand):
    help = 'Build CORE Dial rows (Mode B / Pure Cost) from the consolidated workbook.'

    def add_arguments(self, parser):
        parser.add_argument('--path', default=DEFAULT_WORKBOOK,
                            help=f'Workbook path (default: {DEFAULT_WORKBOOK})')
        parser.add_argument('--scoring-version', default=None,
                            help='Override the scoring_version label taken from the sheet')
        parser.add_argument('--as-at', default=None,
                            help='Assumption-files date (YYYY-MM-DD); defaults to the file mtime date')
        parser.add_argument('--dry-run', action='store_true',
                            help='Parse and validate without writing to the database')
        parser.add_argument('--clear', action='store_true',
                            help='Delete all existing batches and rows first')

    def handle(self, *args, **options):
        path = options['path']
        if not os.path.exists(path):
            self.stderr.write(self.style.ERROR(f'Workbook not found: {path}'))
            return

        as_at = options['as_at']
        if as_at is None:
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            as_at = mtime.date().isoformat()

        self.stdout.write(f'Parsing {path} ...')
        parsed = parse_workbook(path, as_at=as_at)
        scoring_version = options['scoring_version'] or parsed.scoring_version

        self.stdout.write(f'Listings parsed: {len(parsed.listings)}')
        self.stdout.write(f'Scoring version: {scoring_version}')
        self.stdout.write(f'As at:           {as_at}')
        for problem in parsed.problems:
            self.stdout.write(self.style.WARNING(f'  ! {problem}'))

        rows = parsed.dial_rows()
        on_sale_listings = len({r.version_id for r in rows})
        self.stdout.write(f'On-sale listings: {on_sale_listings} '
                          f'({len(rows)} dial rows across 8 states)')
        if parsed.skipped_suppressed:
            self.stdout.write(self.style.WARNING(
                f'Skipped (suppressed): {parsed.skipped_suppressed} on-sale '
                f'listings excluded from the dial.'
            ))

        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS('Dry run — nothing written.'))
            return

        with transaction.atomic():
            if options['clear']:
                CoreDialRow.objects.all().delete()
                CoreDialBatch.objects.all().delete()

            batch, created = CoreDialBatch.objects.get_or_create(
                scoring_version=scoring_version,
                defaults={'as_at': as_at},
            )
            batch.as_at = as_at
            batch.is_current = True
            batch.save()
            CoreDialBatch.objects.exclude(pk=batch.pk).update(is_current=False)

            # Index catalogue vehicles by (make, model, variant, year) for FK links.
            vehicles = {
                (v.brand.lower(), v.model.lower(), v.variant.lower(), v.year): v
                for v in Vehicle.objects.only('id', 'brand', 'model', 'variant', 'year')
            }

            CoreDialRow.objects.filter(batch=batch).delete()
            created_count = 0
            for r in rows:
                vehicle = vehicles.get((r.make.lower(), r.model.lower(), r.variant.lower(), r.year))
                CoreDialRow.objects.create(
                    batch=batch,
                    version_id=r.version_id,
                    model_id=r.model_id,
                    vehicle=vehicle,
                    state=r.state,
                    make=r.make,
                    model=r.model,
                    variant=r.variant,
                    year=r.year,
                    fcai_category=r.fcai_category,
                    driveaway_cents=r.driveaway_cents,
                    coo_pa_cents=r.coo_pa_cents,
                    annual_co2_kg=r.annual_co2_kg,
                    co2_g_per_km=r.co2_g_per_km,
                    price_score=r.price_score,
                    emissions_score=r.emissions_score,
                    co2_cap=r.co2_cap,
                    fuel_cents=r.parts_cents['fuel'],
                    electricity_cents=r.parts_cents['electricity'],
                    ctp_cents=r.parts_cents['ctp'],
                    comprehensive_cents=r.parts_cents['comprehensive'],
                    registration_cents=r.parts_cents['registration'],
                    servicing_cents=r.parts_cents['servicing'],
                    tyres_cents=r.parts_cents['tyres'],
                    road_user_charge_cents=r.parts_cents['road_user_charge'],
                )
                created_count += 1

        linked = CoreDialRow.objects.filter(batch=batch, vehicle__isnull=False).count()
        self.stdout.write(self.style.SUCCESS(
            f'Created batch {scoring_version!r} with {created_count} rows '
            f'({linked} linked to catalogue vehicles).'
        ))
        if parsed.problems:
            self.stdout.write(self.style.WARNING(f'{len(parsed.problems)} warnings (see above).'))
