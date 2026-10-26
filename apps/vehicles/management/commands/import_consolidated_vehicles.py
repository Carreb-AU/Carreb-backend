import os

from django.core.management.base import BaseCommand

from apps.vehicles.services.consolidated_import import import_consolidated_vehicles


class Command(BaseCommand):
    help = (
        'Import the "Consolidated Vehicles v6.4" sheet into the Vehicle catalogue.\n\n'
        'Upserts on (brand, model, variant, year): existing Vehicle UUIDs are kept,\n'
        'new rows are created. Old catalogue rows not present in the sheet are kept.\n'
        'Replaces import_carreb_etl for the 07-Oct-26 workbook format.'
    )

    def add_arguments(self, parser):
        parser.add_argument('filepath', type=str, help='Path to the 02 Vehicles & CORE workbook .xlsx')
        parser.add_argument('--clear', action='store_true', help='Delete ALL Vehicle rows before import')
        parser.add_argument('--dry-run', action='store_true', help='Parse and report only; no database writes')

    def handle(self, *args, **options):
        filepath = options['filepath']

        if not os.path.exists(filepath):
            self.stderr.write(self.style.ERROR(f'File not found: {filepath}'))
            return

        result = import_consolidated_vehicles(
            filepath,
            clear=options['clear'],
            dry_run=options['dry_run'],
        )

        self.stdout.write(
            f"Vehicles seen: {result['vehicles_seen']}, "
            f"states: {result['states']}, modes: {result['modes']}, "
            f"skipped rows: {result['skipped']}"
        )
        self.stdout.write(
            f"created: {result['created']}, updated: {result['updated']}, "
            f"source rows stored: {result['source_rows_written']}"
        )

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('Dry run — nothing was written.'))
        else:
            self.stdout.write(self.style.SUCCESS('Import complete.'))
