from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import RegistrationCategoryBenchmark, RegistrationFeeByState, RegistrationStateFormula


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 18 (RegistrationDefaults) into Registration Category, Fee, & Formula models"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "RegistrationDefaults"
    source_code = "SYNC-SHEET-18-REGISTRATION"
    source_name = "Vehicle Registration Benchmark Specifications & State Fee Schedules"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            RegistrationCategoryBenchmark.objects.all().delete()
            RegistrationFeeByState.objects.all().delete()
            RegistrationStateFormula.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        curr_section = None
        state_headers_sec_b = []

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
                    state_headers_sec_b = []
                    continue
                elif "SECTION C" in c0:
                    curr_section = "C"
                    continue
                elif "SECTION D" in c0:
                    curr_section = None
                    continue

                # Section A: Representative vehicle specs
                if curr_section == "A":
                    if c0.lower() == "fcai_category":
                        continue
                    fcai_cat = c0
                    rep_veh = self._safe_str(row[1])
                    kerb_kg = self._safe_int(row[2]) or 0
                    cylinders = self._safe_int(row[3])
                    engine_l = self._safe_float(row[4])
                    energy_type = self._safe_str(row[5]) or "ICE"
                    total_avg_cents = self._dollars_to_cents(row[6]) if len(row) > 6 else None

                    if not is_dry_run:
                        obj, created = RegistrationCategoryBenchmark.objects.update_or_create(
                            fcai_category=fcai_cat,
                            defaults={
                                "representative_vehicle": rep_veh,
                                "kerb_weight_kg": kerb_kg,
                                "cylinders": cylinders,
                                "engine_l": engine_l,
                                "energy_type": energy_type,
                                "total_avg_cents_pa": total_avg_cents,
                            },
                        )
                        if created: created_count += 1
                        else: updated_count += 1
                    else:
                        created_count += 1

                # Section B: State-by-state registration fees (15 categories x 8 states)
                elif curr_section == "B":
                    if not state_headers_sec_b:
                        # Row header: fcai_category, NSW, VIC, QLD, SA, WA, TAS, NT, ACT
                        state_headers_sec_b = [self._safe_str(c).upper() for c in row[1:9]]
                        continue

                    fcai_cat = c0
                    for s_idx, state_code in enumerate(state_headers_sec_b):
                        col_idx = s_idx + 1
                        if col_idx < len(row):
                            fee_cents = self._dollars_to_cents(row[col_idx])
                            if fee_cents is not None and not is_dry_run:
                                obj, created = RegistrationFeeByState.objects.update_or_create(
                                    fcai_category=fcai_cat,
                                    state=state_code,
                                    defaults={"annual_fee_cents": fee_cents},
                                )
                                if created: created_count += 1
                                else: updated_count += 1
                            else:
                                created_count += 1

                # Section C: Statutory formula notes
                elif curr_section == "C":
                    if c0.lower() == "state":
                        continue
                    state = c0.upper()
                    notes = self._safe_str(row[1]) if len(row) > 1 else ""

                    if not is_dry_run:
                        obj, created = RegistrationStateFormula.objects.update_or_create(
                            state=state,
                            defaults={"basis_notes": notes},
                        )
                        if created: created_count += 1
                        else: updated_count += 1
                    else:
                        created_count += 1

            except Exception as e:
                errors.append(f"Row {r_idx}: {e}")

        return created_count, updated_count, errors
