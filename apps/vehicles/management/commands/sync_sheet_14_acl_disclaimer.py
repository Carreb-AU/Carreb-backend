from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.config.models import ACLComplianceRule


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 14 (ACL_Disclaimer) into ACLComplianceRule"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "ACL_Disclaimer"
    source_code = "SYNC-SHEET-14-ACL-RULES"
    source_name = "Australian Consumer Law Compliance Copywriting Rules"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            ACLComplianceRule.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        order_idx = 0
        for r_idx, row in enumerate(rows, start=1):
            try:
                rule_key = self._safe_str(row[0])
                rule_text = self._safe_str(row[1]) if len(row) > 1 and row[1] is not None else ""

                if not rule_key or not rule_text or "read before" in rule_key.lower():
                    continue

                order_idx += 1
                defaults = {
                    "rule_text": rule_text,
                    "order": order_idx,
                }

                if not is_dry_run:
                    obj, created = ACLComplianceRule.objects.update_or_create(
                        rule_key=rule_key,
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
