from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.config.models import BuildChangelog


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 12 (ChangesFromPriorBuild) into BuildChangelog"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "ChangesFromPriorBuild"
    source_code = "SYNC-SHEET-12-CHANGELOG"
    source_name = "Carreb Build & Calculation Audit Changelog"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            BuildChangelog.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                item = self._safe_str(row[0])
                if not item:
                    continue

                prior = self._safe_str(row[1])
                now_final = self._safe_str(row[2])
                spec = self._safe_str(row[3]) if len(row) > 3 else ""

                defaults = {
                    "prior_build": prior,
                    "now_final": now_final,
                    "spec_source": spec,
                    "order": r_idx,
                }

                if not is_dry_run:
                    obj, created = BuildChangelog.objects.update_or_create(
                        item=item,
                        defaults=defaults,
                    )
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                else:
                    created_count += 1

            except Exception as e:
                errors.append(f"Row {r_idx}: {e}")

        return created_count, updated_count, errors
