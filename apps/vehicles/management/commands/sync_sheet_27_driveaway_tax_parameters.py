from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import DriveawayTaxParameter


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 27 (DriveawayTaxParameters) into DriveawayTaxParameter"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "DriveawayTaxParameters"
    source_code = "SYNC-SHEET-27-TAX-PARAMS"
    source_name = "Luxury Car Tax, State Stamp Duty, and Government Incentive Parameters"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            DriveawayTaxParameter.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                param = self._safe_str(row[hmap.get("parameter", 0)])
                if not param:
                    continue

                val = self._safe_str(row[hmap.get("value", 1)])
                eff_from = self._safe_str(row[hmap.get("effective_from", 2)])
                applies_to = self._safe_str(row[hmap.get("applies_to", 3)])
                source = self._safe_str(row[hmap.get("source", 4)])
                devspec = self._safe_str(row[hmap.get("devspec_ref", 5)])
                note = self._safe_str(row[hmap.get("note", 6)]) if len(row) > 6 else ""

                defaults = {
                    "value": val,
                    "effective_from": eff_from,
                    "applies_to": applies_to,
                    "source": source,
                    "devspec_ref": devspec,
                    "note": note,
                }

                if not is_dry_run:
                    obj, created = DriveawayTaxParameter.objects.update_or_create(
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
