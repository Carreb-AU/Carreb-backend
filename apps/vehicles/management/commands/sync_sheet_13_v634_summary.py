from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.config.models import ReleaseSummaryMetric


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 13 (v6.3.4 Summary) into ReleaseSummaryMetric"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "v6.3.4 Summary"
    source_code = "SYNC-SHEET-13-SUMMARY"
    source_name = "Carreb v6.3.4 Operational & Architectural Release Summary"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            ReleaseSummaryMetric.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        current_section = "CORE METRICS"
        order_idx = 0

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                c0 = self._safe_str(row[0])
                c1 = self._safe_str(row[1]) if len(row) > 1 and row[1] is not None else ""

                if not c0:
                    continue

                # Detect Section divider banners
                if "CORE MODE" in c0:
                    current_section = "CORE MODE"
                    continue
                elif "FINANCE DEFAULTS" in c0:
                    current_section = "FINANCE DEFAULTS"
                    continue
                elif "SCORING" in c0:
                    current_section = "SCORING"
                    continue
                elif "REGRESSION SPOT-CHECKS" in c0:
                    current_section = "REGRESSION SPOT-CHECKS"
                    continue
                elif "STAR DISTRIBUTION" in c0:
                    current_section = "STAR DISTRIBUTION"
                    continue
                elif "DOCUMENT MAP" in c0:
                    current_section = "DOCUMENT MAP"
                    continue
                elif "ACL DISCLAIMER" in c0:
                    current_section = "ACL DISCLAIMER"
                    continue
                elif "KNOWN RECONCILIATION GAP" in c0:
                    if "Per-category ratio" in c0:
                        current_section = "KNOWN RECONCILIATION GAP (Per-category ratio)"
                    else:
                        current_section = "KNOWN RECONCILIATION GAP"
                    continue

                order_idx += 1
                defaults = {
                    "value": c1,
                    "order": order_idx,
                }

                if not is_dry_run:
                    obj, created = ReleaseSummaryMetric.objects.update_or_create(
                        section=current_section,
                        metric=c0,
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
