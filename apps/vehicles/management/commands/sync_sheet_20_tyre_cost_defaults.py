from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import TyreCategoryDefault


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 20 (TyreCostDefaults) into TyreCategoryDefault"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "TyreCostDefaults"
    source_code = "SYNC-SHEET-20-TYRES"
    source_name = "Tyre Specifications, Replacement Intervals, and Cost Defaults"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            TyreCategoryDefault.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                fcai_cat = self._safe_str(row[hmap.get("fcai_category", 0)])
                if not fcai_cat:
                    continue

                size = self._safe_str(row[hmap.get("typical_tyre_size", 1)])
                cost_set_cents = self._dollars_to_cents(row[hmap.get("cost_per_set_4_aud", 2)]) or 0
                interval_km = self._safe_int(row[hmap.get("replacement_interval_km", 3)]) or 50000
                annual_cents = self._dollars_to_cents(row[hmap.get("annualised_cost_aud", 4)]) or 0
                source = self._safe_str(row[hmap.get("source", 5)]) if "source" in hmap else ""

                defaults = {
                    "typical_tyre_size": size,
                    "cost_per_set_4_cents": cost_set_cents,
                    "replacement_interval_km": interval_km,
                    "annualised_cost_cents": annual_cents,
                    "source": source,
                }

                if not is_dry_run:
                    obj, created = TyreCategoryDefault.objects.update_or_create(
                        fcai_category=fcai_cat,
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
