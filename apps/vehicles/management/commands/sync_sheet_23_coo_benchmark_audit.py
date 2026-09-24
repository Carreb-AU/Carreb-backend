from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import COOBenchmarkAudit


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 23 (COOBenchmarkAudit) into COOBenchmarkAudit"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "COOBenchmarkAudit"
    source_code = "SYNC-SHEET-23-COO-AUDIT"
    source_name = "Cost of Ownership Baseline Benchmarks by Category & State"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            COOBenchmarkAudit.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).upper() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                fcai_cat = self._safe_str(row[0])
                if not fcai_cat or "note" in fcai_cat.lower() or "sources" in fcai_cat.lower() or "annual coo" in fcai_cat.lower() or "input" in fcai_cat.lower():
                    continue

                nsw = self._dollars_to_cents(self._row_val(row, hmap, "NSW", self._safe_str(row[1]) if len(row) > 1 else None)) or 0
                vic = self._dollars_to_cents(self._row_val(row, hmap, "VIC", self._safe_str(row[2]) if len(row) > 2 else None)) or 0
                qld = self._dollars_to_cents(self._row_val(row, hmap, "QLD", self._safe_str(row[3]) if len(row) > 3 else None)) or 0
                sa = self._dollars_to_cents(self._row_val(row, hmap, "SA", self._safe_str(row[4]) if len(row) > 4 else None)) or 0
                wa = self._dollars_to_cents(self._row_val(row, hmap, "WA", self._safe_str(row[5]) if len(row) > 5 else None)) or 0
                tas = self._dollars_to_cents(self._row_val(row, hmap, "TAS", self._safe_str(row[6]) if len(row) > 6 else None)) or 0
                nt = self._dollars_to_cents(self._row_val(row, hmap, "NT", self._safe_str(row[7]) if len(row) > 7 else None)) or 0
                act = self._dollars_to_cents(self._row_val(row, hmap, "ACT", self._safe_str(row[8]) if len(row) > 8 else None)) or nsw

                profile = "Commercial (30k km)" if "commercial" in fcai_cat.lower() else "Standard"

                defaults = {
                    "nsw_coo_cents": nsw,
                    "vic_coo_cents": vic,
                    "qld_coo_cents": qld,
                    "sa_coo_cents": sa,
                    "wa_coo_cents": wa,
                    "tas_coo_cents": tas,
                    "nt_coo_cents": nt,
                    "act_coo_cents": act,
                    "km_per_year_used": 30000 if profile == "Commercial (30k km)" else None,
                }

                if not is_dry_run:
                    obj, created = COOBenchmarkAudit.objects.update_or_create(
                        fcai_category=fcai_cat,
                        usage_profile=profile,
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
