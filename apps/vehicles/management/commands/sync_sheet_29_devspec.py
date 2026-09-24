from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.config.models import DevSpecTraceMap


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 29 (DevSpec_TraceMap) into DevSpecTraceMap"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "DevSpec_TraceMap"
    source_code = "SYNC-SHEET-29-DEVSPEC-TRACE"
    source_name = "System Architecture & Specification Traceability Matrix"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            DevSpecTraceMap.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                item_num = self._safe_int(row[hmap.get("#", 0)]) or (r_idx - 1)
                tab_name = self._safe_str(row[hmap.get("workbook_tab", 1)])
                if not tab_name:
                    continue

                feeds = self._safe_str(row[hmap.get("feeds (ui / engine)", 2)]) or self._safe_str(row[2])
                dev_spec = self._safe_str(row[hmap.get("dev_spec_section", 3)])
                calc_spec = self._safe_str(row[hmap.get("calc_spec_section", 4)])
                source = self._safe_str(row[hmap.get("source_of_truth", 5)])
                notes = self._safe_str(row[hmap.get("notes", 6)]) if len(row) > 6 else ""

                defaults = {
                    "item_number": item_num,
                    "feeds": feeds,
                    "dev_spec_section": dev_spec,
                    "calc_spec_section": calc_spec,
                    "source_of_truth": source,
                    "notes": notes,
                }

                if not is_dry_run:
                    obj, created = DevSpecTraceMap.objects.update_or_create(
                        workbook_tab=tab_name,
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
