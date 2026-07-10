import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.vehicles.models import Vehicle

class Command(BaseCommand):
    help = 'Import image URLs from a dump file'

    def add_arguments(self, parser):
        parser.add_argument('filepath', type=str, help='Path to Excel file (e.g., carreb-core-dump (1).xlsx)')

    @transaction.atomic
    def handle(self, *args, **options):
        filepath = options['filepath']
        
        self.stdout.write("Loading workbook...")
        try:
            # The new dump file has a sheet named 'CORE Baselines'
            df = pd.read_excel(filepath, sheet_name='CORE Baselines')
        except Exception as e:
            self.stderr.write(f"Error reading Excel file: {e}")
            return
            
        if 'Image url ' not in df.columns:
            self.stderr.write("Column 'Image url ' not found in the spreadsheet.")
            return

        updated_count = 0
        missing_count = 0
        
        for _, row in df.iterrows():
            make = str(row.get('Make')).strip() if not pd.isna(row.get('Make')) else ''
            model = str(row.get('Model')).strip() if not pd.isna(row.get('Model')) else ''
            variant = str(row.get('Variant')).strip() if not pd.isna(row.get('Variant')) else ''
            
            year_val = row.get('Year')
            year = int(float(year_val)) if not pd.isna(year_val) and year_val != '' else 2026
            
            image_url = str(row.get('Image url ')).strip() if not pd.isna(row.get('Image url ')) else ''
            
            if image_url:
                # Find the vehicle and update it
                vehicles = Vehicle.objects.filter(
                    brand__iexact=make,
                    model__iexact=model,
                    variant__iexact=variant,
                    year=year
                )
                
                if vehicles.exists():
                    vehicles.update(image_url=image_url)
                    updated_count += vehicles.count()
                else:
                    missing_count += 1
                    
        self.stdout.write(self.style.SUCCESS(f"Successfully updated {updated_count} vehicles with image URLs!"))
        if missing_count > 0:
            self.stdout.write(self.style.WARNING(f"Could not find matching DB records for {missing_count} rows in the spreadsheet."))
