from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import CategoryAnnualKMBenchmark, StateAnnualKMBenchmark


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 22 (AnnualKMByCategory) into Category & State Annual KM Benchmark models"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "AnnualKMByCategory"
    source_code = "SYNC-SHEET-22-ANNUAL-KM"
    source_name = "Estimated Annual Travel Distance by Vehicle Category and State"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            CategoryAnnualKMBenchmark.objects.all().delete()
            StateAnnualKMBenchmark.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        curr_section = None
        for r_idx, row in enumerate(rows, start=1):
            try:
                c0 = self._safe_str(row[0])
                if not c0:
                    continue

                if "SECTION A" in c0:
                    curr_section = "A"
                    continue
                elif "SECTION B" in c0:
                    curr_section = "B"
                    continue
                elif "SECTION C" in c0:
                    curr_section = None
                    continue

                if c0.lower() in ("fcai_category", "state"):
                    continue

                # Section A: Category annual km
                if curr_section == "A":
                    fcai_cat = c0
                    est_km = self._safe_int(row[1]) or 13300
                    basis = self._safe_str(row[2])
                    abs_anchor = self._safe_str(row[3])
                    vs_flat_17k = self._safe_str(row[4])
                    impact = self._safe_str(row[5])
                    confidence = self._safe_str(row[6]) if len(row) > 6 else ""
                    source = self._safe_str(row[7]) if len(row) > 7 else ""

                    if not is_dry_run:
                        obj, created = CategoryAnnualKMBenchmark.objects.update_or_create(
                            fcai_category=fcai_cat,
                            defaults={
                                "est_annual_km": est_km,
                                "basis_pattern": basis,
                                "abs_anchor": abs_anchor,
                                "vs_flat_17k": vs_flat_17k,
                                "impact_on_coo": impact,
                                "confidence": confidence,
                                "source": source,
                            },
                        )
                        if created: created_count += 1
                        else: updated_count += 1
                    else:
                        created_count += 1

                # Section B: State annual km
                elif curr_section == "B":
                    state = c0.upper()
                    avg_km = self._safe_int(row[1]) or 12100
                    vs_nat = self._safe_str(row[2])
                    source = self._safe_str(row[3]) if len(row) > 3 else ""

                    if not is_dry_run:
                        obj, created = StateAnnualKMBenchmark.objects.update_or_create(
                            state=state,
                            defaults={
                                "avg_km_per_vehicle": avg_km,
                                "vs_national": vs_nat,
                                "source": source,
                            },
                        )
                        if created: created_count += 1
                        else: updated_count += 1
                    else:
                        created_count += 1

            except Exception as e:
                errors.append(f"Row {r_idx}: {e}")

        return created_count, updated_count, errors
