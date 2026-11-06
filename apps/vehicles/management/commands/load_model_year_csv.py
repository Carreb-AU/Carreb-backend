"""Load model-year (MY) labels for catalogue vehicles from a client CSV (B-01).

The Consolidated workbook carries no MY column, so the MY labels arrive as a
separate lookup file. Expected columns (header row, any case, any order):

    make, model, variant, year, model_year

`model_year` is the badge label (e.g. "MY25"); `my_year` is derived from it
for the type-ahead's year-or-MY matching, and rows render as
"2025 (MY25) Make Model Variant".

Usage:
    python manage.py load_model_year_csv <path-to.csv> [--dry-run]
"""
import csv

from django.core.management.base import BaseCommand

from apps.vehicles.models import Vehicle, model_year_from_label


class Command(BaseCommand):
    help = "Populate Vehicle.model_year/my_year from a client MY lookup CSV (B-01)."

    def add_arguments(self, parser):
        parser.add_argument('path', help="CSV with make, model, variant, year, model_year columns")
        parser.add_argument('--dry-run', action='store_true',
                            help="Report matches without writing")

    def handle(self, *args, **options):
        matched, missed = 0, []
        with open(options['path'], newline='', encoding='utf-8-sig') as fh:
            for row in csv.DictReader(fh):
                fields = {k.strip().lower(): (v or '').strip()
                          for k, v in row.items() if k}
                try:
                    make = fields['make']
                    model = fields['model']
                    variant = fields['variant']
                    year = int(float(fields['year']))
                    label = fields['model_year']
                except (KeyError, ValueError):
                    missed.append(f"unparseable row: {row}")
                    continue
                if not label:
                    continue
                vehicle = Vehicle.objects.filter(
                    brand__iexact=make, model__iexact=model,
                    variant__iexact=variant, year=year).first()
                if not vehicle:
                    missed.append(f"{make} {model} {variant} {year}")
                    continue
                matched += 1
                if not options['dry_run']:
                    vehicle.model_year = label[:50]
                    vehicle.my_year = model_year_from_label(label)
                    vehicle.save(update_fields=['model_year', 'my_year'])

        self.stdout.write(self.style.SUCCESS(
            f"Matched {matched} vehicles; {len(missed)} unmatched."))
        for m in missed[:20]:
            self.stdout.write(self.style.WARNING(f"  ! {m}"))
        if len(missed) > 20:
            self.stdout.write(self.style.WARNING(f"  ! ... and {len(missed) - 20} more"))
