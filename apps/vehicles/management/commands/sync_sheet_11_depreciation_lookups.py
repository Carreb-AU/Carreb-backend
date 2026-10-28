from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import DepreciationLookup


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 11 (DepreciationLookups) from Carreb Calc Workbook v6.4"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "DepreciationLookups"
    source_code = "SYNC-SHEET-11-DEPRECIATION"
    source_name = "3-Layer Depreciation Benchmark Lookups"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            DepreciationLookup.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                layer = self._safe_str(row[hmap.get("layer", 0)])
                key = self._safe_str(row[hmap.get("key", 1)])
                if not layer or not key:
                    continue
                if self._is_annotation_row(row, hmap, ["layer", "key"], ["modifier", "source"]):
                    continue

                modifier = self._safe_float(row[hmap.get("modifier", 2)]) or 1.0
                source = self._safe_str(row[hmap.get("source", 3)])

                # Determine layer_num
                layer_num = 1
                if "layer 2" in layer.lower():
                    layer_num = 2
                elif "layer 3" in layer.lower():
                    layer_num = 3

                # Determine powertrain qualifier if present
                powertrain = ""
                if layer_num == 2:
                    powertrain = key.lower()
                elif layer_num == 3 and "(" in key:
                    powertrain = key.split("(")[-1].replace(")", "").strip().lower()

                defaults = {
                    "layer_num": layer_num,
                    "powertrain_type": powertrain,
                    "modifier": modifier,
                    "source": source,
                }

                if not is_dry_run:
                    obj, created = DepreciationLookup.objects.update_or_create(
                        layer=layer,
                        key=key,
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
