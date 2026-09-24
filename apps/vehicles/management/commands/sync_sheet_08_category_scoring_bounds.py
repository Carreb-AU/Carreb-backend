from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import CategoryScoringBounds


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 8 (CategoryScoringBounds) from Carreb Calc Workbook v6.4"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "CategoryScoringBounds"
    source_code = "SYNC-SHEET-08-SCORING-BOUNDS"
    source_name = "CORE Score Normalisation & Outlier Bounds"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            CategoryScoringBounds.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c) for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                fcai_cat = self._safe_str(row[hmap.get("fcai_category", 0)])
                core_mode = self._safe_str(row[hmap.get("core_mode", 1)]).upper()
                if not fcai_cat or not core_mode:
                    continue

                v_count = self._safe_int(row[hmap.get("vehicle_count", 2)]) or 0
                cat_min_coo = self._safe_float(row[hmap.get("cat_min_coo", 3)]) or 0.0
                cat_max_coo = self._safe_float(row[hmap.get("cat_max_coo", 4)]) or 0.0
                act_min_coo = self._safe_float(row[hmap.get("actual_min_coo", 5)])
                act_max_coo = self._safe_float(row[hmap.get("actual_max_coo", 6)])
                cat_min_co2 = self._safe_float(row[hmap.get("cat_min_co2", 7)]) or 0.0
                cat_max_co2 = self._safe_float(row[hmap.get("cat_max_co2", 8)]) or 0.0
                scoring_ver = self._safe_str(row[hmap.get("scoring_version", 9)]) or "v6.3.4-cat-norm"

                defaults = {
                    "vehicle_count": v_count,
                    "cat_min_coo": cat_min_coo,
                    "cat_max_coo": cat_max_coo,
                    "actual_min_coo": act_min_coo,
                    "actual_max_coo": act_max_coo,
                    "cat_min_co2": cat_min_co2,
                    "cat_max_co2": cat_max_co2,
                }

                if not is_dry_run:
                    obj, created = CategoryScoringBounds.objects.update_or_create(
                        fcai_category=fcai_cat,
                        core_mode=core_mode,
                        scoring_version=scoring_ver,
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
