from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.config.models import SubstantiationSourceRegistry


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 25 (_Sources_Index) into SubstantiationSourceRegistry"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "_Sources_Index"
    source_code = "SYNC-SHEET-25-SOURCES-INDEX"
    source_name = "Master Sources & ACCC Substantiation Index"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            SubstantiationSourceRegistry.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        order_idx = 0
        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                cat = self._safe_str(row[hmap.get("data_category", 0)])
                if not cat:
                    continue
                if self._is_annotation_row(row, hmap, ["data_category"], [
                    "carreb_table_or_sheet", "primary_source", "url_or_publisher",
                    "data_period_in_dump", "refresh_cadence", "accc_substantiation_class",
                ]):
                    continue

                sheet_ref = self._safe_str(row[hmap.get("carreb_table_or_sheet", 1)])
                primary_src = self._safe_str(row[hmap.get("primary_source", 2)])
                url_pub = self._safe_str(row[hmap.get("url_or_publisher", 3)])
                period = self._safe_str(row[hmap.get("data_period_in_dump", 4)])
                cadence = self._safe_str(row[hmap.get("refresh_cadence", 5)])
                substantiation = self._safe_str(row[hmap.get("accc_substantiation_class", 6)])

                order_idx += 1
                defaults = {
                    "carreb_table_or_sheet": sheet_ref,
                    "primary_source": primary_src,
                    "url_or_publisher": url_pub,
                    "data_period_in_dump": period,
                    "refresh_cadence": cadence,
                    "accc_substantiation_class": substantiation,
                    "order": order_idx,
                }

                if not is_dry_run:
                    obj, created = SubstantiationSourceRegistry.objects.update_or_create(
                        data_category=cat,
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
