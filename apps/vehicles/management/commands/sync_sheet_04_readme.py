from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import DataSource


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 4 (README) from Carreb Calc Workbook v6.4 into Documentation & Spec Metadata"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "README"
    source_code = "SYNC-SHEET-04-README"
    source_name = "Carreb v6.4 Launch Documentation & README"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        rows = list(sheet.iter_rows(values_only=True))

        metadata_dict = {}
        for row in rows:
            if not row or not row[0]:
                continue
            k = self._safe_str(row[0])
            v = self._safe_str(row[1]) if len(row) > 1 and row[1] is not None else ""
            if k:
                metadata_dict[k] = v

        self.stdout.write(f"Parsed {len(metadata_dict)} README spec parameters.")

        if not is_dry_run:
            ds, created = DataSource.objects.update_or_create(
                code="DOC-CARREB-V64-README",
                defaults={
                    "name": "Carreb v6.4 Release Specifications",
                    "dataset_type": "xlsx",
                    "metadata": metadata_dict,
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
