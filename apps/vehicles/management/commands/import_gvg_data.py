import os
from django.core.management.base import BaseCommand
from apps.vehicles.services.gvg_import import (
    import_all,
    import_category_cost_defaults,
    import_gvg_xlsx,
    import_old_fuel_consumption_csv,
)


class Command(BaseCommand):
    help = (
        'Import Green Vehicle Guide data and category cost defaults.\n\n'
        'Modes:\n'
        '  all     --workbook PATH --gvg-xlsx PATH --old-csv PATH\n'
        '  defaults --workbook PATH\n'
        '  current --gvg-xlsx PATH\n'
        '  older   --old-csv PATH\n'
    )

    def add_arguments(self, parser):
        parser.add_argument('mode', choices=['all', 'defaults', 'current', 'older'])
        parser.add_argument('--workbook', type=str, help='Path to Carreb Calc Workbook .xlsx')
        parser.add_argument('--gvg-xlsx', type=str, help='Path to GVG-Vehicles-2004-2025.xlsx')
        parser.add_argument('--old-csv', type=str, help='Path to FuelConsumptionGuide1986-2003.csv')
        parser.add_argument('--clear', action='store_true', help='Clear existing records for the target dataset(s) before import')

    def handle(self, *args, **options):
        mode = options['mode']
        clear = options['clear']

        if mode in ('all', 'defaults'):
            workbook = options.get('workbook')
            if not workbook:
                self.stderr.write(self.style.ERROR('--workbook is required for this mode'))
                return
            if not os.path.exists(workbook):
                self.stderr.write(self.style.ERROR(f'Workbook not found: {workbook}'))
                return

        if mode in ('all', 'current'):
            gvg_xlsx = options.get('gvg_xlsx')
            if not gvg_xlsx:
                self.stderr.write(self.style.ERROR('--gvg-xlsx is required for this mode'))
                return
            if not os.path.exists(gvg_xlsx):
                self.stderr.write(self.style.ERROR(f'GVG xlsx not found: {gvg_xlsx}'))
                return

        if mode in ('all', 'older'):
            old_csv = options.get('old_csv')
            if not old_csv:
                self.stderr.write(self.style.ERROR('--old-csv is required for this mode'))
                return
            if not os.path.exists(old_csv):
                self.stderr.write(self.style.ERROR(f'Old CSV not found: {old_csv}'))
                return

        if mode == 'all':
            results = import_all(
                workbook_path=workbook,
                gvg_xlsx_path=gvg_xlsx,
                old_csv_path=old_csv,
                clear=clear,
            )
            self.stdout.write('Category defaults created/updated: {}'.format(results['category_defaults']))
            self.stdout.write('GVG current: created={created}, updated={updated}, skipped={skipped}'.format(**results['gvg_current']))
            self.stdout.write('GVG older: created={created}, updated={updated}, skipped={skipped}'.format(**results['gvg_older']))

        elif mode == 'defaults':
            count = import_category_cost_defaults(workbook, clear=clear)
            self.stdout.write(self.style.SUCCESS(f'Category defaults created/updated: {count}'))

        elif mode == 'current':
            result = import_gvg_xlsx(gvg_xlsx, clear=clear)
            self.stdout.write(self.style.SUCCESS(
                f'GVG current: created={result["created"]}, updated={result["updated"]}, skipped={result["skipped"]}'
            ))

        elif mode == 'older':
            result = import_old_fuel_consumption_csv(old_csv, clear=clear)
            self.stdout.write(self.style.SUCCESS(
                f'GVG older: created={result["created"]}, updated={result["updated"]}, skipped={result["skipped"]}'
            ))

        self.stdout.write(self.style.SUCCESS('Import complete.'))
