from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import DataSource


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 2 (Lists) from Market Gap-Fill Dataset into Reference Validation Metadata"
    default_workbook_path = "Carreb - Market Gap-Fill Dataset TEMPLATE v1.0.xlsx"
    sheet_name = "Lists"
    source_code = "SYNC-SHEET-02-FIELD-DEFS"
    source_name = "Market Gap-Fill Dropdown Reference Lists"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 3:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c) for c in rows[2] if self._safe_str(c)]
        lists_data = {h: [] for h in headers}

        for row in rows[3:]:
            for idx, h in enumerate(headers):
                if idx < len(row):
                    val = self._safe_str(row[idx])
                    if val and val not in lists_data[h]:
                        lists_data[h].append(val)

        self.stdout.write(f"Parsed {len(headers)} reference lists: {list(lists_data.keys())}")

        if not is_dry_run:
            ds, created = DataSource.objects.update_or_create(
                code="REF-GAPFILL-LISTS",
                defaults={
                    "name": "Gap-Fill Schema Dropdown Lists",
                    "dataset_type": "xlsx",
                    "metadata": lists_data,
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
