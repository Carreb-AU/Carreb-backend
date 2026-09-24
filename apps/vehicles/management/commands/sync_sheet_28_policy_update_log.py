from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.config.models import PolicyUpdateLog


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 28 (v6.4 Policy Update Log) into PolicyUpdateLog"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "v6.4 Policy Update Log"
    source_code = "SYNC-SHEET-28-POLICY-LOG"
    source_name = "Policy & Regulatory Update Audit Ledger"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            PolicyUpdateLog.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                item_num = self._safe_int(row[hmap.get("#", 0)]) or (r_idx - 1)
                param = self._safe_str(row[hmap.get("parameter", 1)])
                if not param:
                    continue

                tab_aff = self._safe_str(row[hmap.get("tab_affected", 2)])
                old_val = self._safe_str(row[hmap.get("old_value", 3)])
                new_val = self._safe_str(row[hmap.get("new_value_at_2026_07_10", 4)]) or self._safe_str(row[4])
                eff_date = self._safe_str(row[hmap.get("effective_date", 5)])
                source = self._safe_str(row[hmap.get("source", 6)])
                spec_ref = self._safe_str(row[hmap.get("spec_ref", 7)])
                reason = self._safe_str(row[hmap.get("reason", 8)]) if "reason" in hmap else ""
                status = self._safe_str(row[hmap.get("status", 9)]) if "status" in hmap else "APPLIED"

                defaults = {
                    "tab_affected": tab_aff,
                    "old_value": old_val,
                    "new_value": new_val,
                    "effective_date": eff_date,
                    "source": source,
                    "spec_ref": spec_ref,
                    "reason": reason,
                    "status": status or "APPLIED",
                }

                if not is_dry_run:
                    obj, created = PolicyUpdateLog.objects.update_or_create(
                        item_number=item_num,
                        parameter=param,
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
