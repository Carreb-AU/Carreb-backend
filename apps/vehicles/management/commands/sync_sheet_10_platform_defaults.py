from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.config.models import PlatformDefault


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 10 (PlatformDefaults) from Carreb Calc Workbook v6.4"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "PlatformDefaults"
    source_code = "SYNC-SHEET-10-PLATFORM-DEFAULTS"
    source_name = "Global Platform Calculation Defaults"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            PlatformDefault.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c) for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                config_key = self._safe_str(row[hmap.get("config_key", 0)])
                if not config_key:
                    continue
                if self._is_annotation_row(row, hmap, ["config_key"], [
                    "config_value", "config_type", "source_label", "last_updated", "description",
                ]):
                    continue

                config_val = self._safe_str(row[hmap.get("config_value", 1)])
                config_type = self._safe_str(row[hmap.get("config_type", 2)]) or "string"
                source_lbl = self._safe_str(row[hmap.get("source_label", 3)])
                last_updated = self._parse_date(row[hmap.get("last_updated", 4)])
                desc = self._safe_str(row[hmap.get("description", 5)])

                defaults = {
                    "config_value": config_val,
                    "config_type": config_type,
                    "source_label": source_lbl,
                    "last_updated": last_updated,
                    "description": desc,
                }

                if not is_dry_run:
                    obj, created = PlatformDefault.objects.update_or_create(
                        config_key=config_key,
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
