from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import FinanceDefault


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 9 (FinanceDefaults) from Carreb Calc Workbook v6.4"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "FinanceDefaults"
    source_code = "SYNC-SHEET-09-FINANCE-DEFAULTS"
    source_name = "Finance Defaults by Broad Category"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            FinanceDefault.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c) for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                cat_broad = self._safe_str(row[hmap.get("fcai_category_broad", 0)])
                if not cat_broad:
                    continue
                if self._is_annotation_row(row, hmap, ["fcai_category_broad"], [
                    "deposit_pct", "base_rate_pct", "alt_fuel_modifier_pct", "term_months",
                    "balloon_pct", "estab_fee_default", "estab_fee_bev", "admin_fee_monthly",
                    "effective_from", "source",
                ]):
                    continue

                dep_pct = self._safe_float(row[hmap.get("deposit_pct", 1)]) or 10.0
                base_rate = self._safe_float(row[hmap.get("base_rate_pct", 2)]) or 7.5
                alt_fuel_mod = self._safe_float(row[hmap.get("alt_fuel_modifier_pct", 3)]) or -1.5
                term = self._safe_int(row[hmap.get("term_months", 4)]) or 60
                balloon = self._safe_float(row[hmap.get("balloon_pct", 5)]) or 0.0

                # Integer cents conversion for monetary fees
                estab_def = self._dollars_to_cents(row[hmap.get("estab_fee_default", 6)]) or 40000
                estab_bev = self._dollars_to_cents(row[hmap.get("estab_fee_bev", 7)]) or 30000
                admin_fee = self._dollars_to_cents(row[hmap.get("admin_fee_monthly", 8)]) or 1000

                eff_from = self._parse_date(row[hmap.get("effective_from", 9)]) if "effective_from" in hmap else None
                source = self._safe_str(row[hmap.get("source", 10)]) if "source" in hmap else ""

                defaults = {
                    "deposit_pct": dep_pct,
                    "base_rate_pct": base_rate,
                    "alt_fuel_modifier_pct": alt_fuel_mod,
                    "term_months": term,
                    "balloon_pct": balloon,
                    "estab_fee_default": estab_def,
                    "estab_fee_bev": estab_bev,
                    "admin_fee_monthly": admin_fee,
                    "effective_from": eff_from,
                    "source": source,
                }

                if not is_dry_run:
                    obj, created = FinanceDefault.objects.update_or_create(
                        fcai_category_broad=cat_broad,
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
