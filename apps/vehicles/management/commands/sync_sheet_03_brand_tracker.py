from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import DataSource


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 3 (Brand tracker) from Market Gap-Fill Dataset into Progress Audit Metadata"
    default_workbook_path = "Carreb - Market Gap-Fill Dataset TEMPLATE v1.0.xlsx"
    sheet_name = "Brand tracker"
    source_code = "SYNC-SHEET-03-BRAND-TRACKER"
    source_name = "Market Gap-Fill Brand Progress Tracker"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 3:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c) for c in rows[2] if self._safe_str(c)]
        brand_entries = []

        for idx, row in enumerate(rows[3:], start=4):
            brand = self._safe_str(row[0]) if len(row) > 0 else ""
            if not brand or "total" in brand.lower():
                continue
            models_found = self._safe_int(row[1]) if len(row) > 1 else None
            variants = self._safe_int(row[2]) if len(row) > 2 else None
            source_used = self._safe_str(row[3]) if len(row) > 3 else ""
            date_completed = self._safe_str(row[4]) if len(row) > 4 else ""
            notes = self._safe_str(row[5]) if len(row) > 5 else ""

            brand_entries.append({
                "brand": brand,
                "models_found": models_found,
                "variants_recorded": variants,
                "primary_source_used": source_used,
                "date_completed": date_completed,
                "notes": notes,
            })

        self.stdout.write(f"Parsed {len(brand_entries)} brand tracker progress rows.")

        if not is_dry_run:
            ds, created = DataSource.objects.update_or_create(
                code="TRACKER-GAPFILL-BRANDS",
                defaults={
                    "name": "Gap-Fill Ingestion Brand Tracker",
                    "dataset_type": "xlsx",
                    "metadata": {"entries": brand_entries, "count": len(brand_entries)},
                    "is_active": True,
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1
        else:
            created_count += 1

        return created_count, updated_count, errors
