from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import MaintenanceCategoryDefault


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 19 (MaintenanceDefaults) into MaintenanceCategoryDefault"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "MaintenanceDefaults"
    source_code = "SYNC-SHEET-19-MAINTENANCE"
    source_name = "Scheduled Servicing & Maintenance Benchmarks by Category"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            MaintenanceCategoryDefault.objects.all().delete()

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

                rep_veh = self._safe_str(row[hmap.get("representative_vehicle", 1)])
                interval = self._safe_str(row[hmap.get("service_interval", 2)])

                five_yr_cents = self._dollars_to_cents(row[hmap.get("five_year_total_aud", 3)]) or 0
                annual_avg_cents = self._dollars_to_cents(row[hmap.get("annual_avg_aud", 4)]) or 0
                year1_cents = self._dollars_to_cents(row[hmap.get("year1_aud", 5)]) or 0
                year5_cents = self._dollars_to_cents(row[hmap.get("year5_aud", 6)]) or 0
                source = self._safe_str(row[hmap.get("source", 7)]) if "source" in hmap else ""

                defaults = {
                    "representative_vehicle": rep_veh,
                    "service_interval": interval,
                    "five_year_total_cents": five_yr_cents,
                    "annual_avg_cents": annual_avg_cents,
                    "year1_cents": year1_cents,
                    "year5_cents": year5_cents,
                    "source": source,
                }

                if not is_dry_run:
                    obj, created = MaintenanceCategoryDefault.objects.update_or_create(
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
