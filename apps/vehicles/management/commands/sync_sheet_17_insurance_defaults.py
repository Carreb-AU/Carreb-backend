from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import CTPStateDefault, InsuranceCategoryBenchmark, InsuranceStateModifier


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 17 (InsuranceDefaults) into CTPStateDefault, InsuranceCategoryBenchmark, & InsuranceStateModifier"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "InsuranceDefaults"
    source_code = "SYNC-SHEET-17-INSURANCE"
    source_name = "CTP and Comprehensive Insurance Defaults by State & Category"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            CTPStateDefault.objects.all().delete()
            InsuranceCategoryBenchmark.objects.all().delete()
            InsuranceStateModifier.objects.all().delete()

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
                    curr_section = "C"
                    continue
                elif "SECTION D" in c0 or "SECTION E" in c0:
                    curr_section = None
                    continue

                if c0.lower() in ("state", "fcai_category"):
                    continue

                # Section A: CTP by state
                if curr_section == "A":
                    state = c0.upper()
                    annual_ctp_cents = self._dollars_to_cents(row[1]) or 0
                    bundled = self._safe_str(row[2])
                    notes = self._safe_str(row[3])
                    source = self._safe_str(row[4])

                    if not is_dry_run:
                        obj, created = CTPStateDefault.objects.update_or_create(
                            state=state,
                            defaults={
                                "annual_ctp_cents": annual_ctp_cents,
                                "bundled_in_rego": bundled,
                                "notes": notes,
                                "source": source,
                            },
                        )
                        if created: created_count += 1
                        else: updated_count += 1
                    else:
                        created_count += 1

                # Section B: Comprehensive benchmark by category
                elif curr_section == "B":
                    fcai_cat = c0
                    nat_avg_cents = self._dollars_to_cents(row[1]) or 0
                    est_monthly_cents = self._dollars_to_cents(row[2]) or 0
                    basis = self._safe_str(row[3])
                    source = self._safe_str(row[4])

                    if not is_dry_run:
                        obj, created = InsuranceCategoryBenchmark.objects.update_or_create(
                            fcai_category=fcai_cat,
                            defaults={
                                "national_avg_cents_pa": nat_avg_cents,
                                "estimated_monthly_cents": est_monthly_cents,
                                "representative_basis": basis,
                                "source": source,
                            },
                        )
                        if created: created_count += 1
                        else: updated_count += 1
                    else:
                        created_count += 1

                # Section C: State modifiers
                elif curr_section == "C":
                    state = c0.upper()
                    avg_comp_cents = self._dollars_to_cents(row[1]) or 0
                    nat_avg_cents = self._dollars_to_cents(row[2]) or 0
                    modifier = self._safe_float(row[3]) or 1.0
                    rel_to_nat = self._safe_str(row[4])
                    explanation = self._safe_str(row[5]) if len(row) > 5 else ""
                    source = self._safe_str(row[6]) if len(row) > 6 else ""

                    if not is_dry_run:
                        obj, created = InsuranceStateModifier.objects.update_or_create(
                            state=state,
                            defaults={
                                "avg_comprehensive_cents": avg_comp_cents,
                                "national_avg_cents": nat_avg_cents,
                                "state_modifier": modifier,
                                "relative_to_national": rel_to_nat,
                                "explanation": explanation,
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
