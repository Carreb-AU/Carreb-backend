from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import FCAICategoryRegistry


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 15 (FCAICategoryRegistry) into FCAICategoryRegistry"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "FCAICategoryRegistry"
    source_code = "SYNC-SHEET-15-FCAI-REGISTRY"
    source_name = "Official 27 FCAI VFACTS Vehicle Category Registry"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            FCAICategoryRegistry.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                segment_id = self._safe_int(row[hmap.get("#", 0)])
                fcai_seg = self._safe_str(row[hmap.get("fcai_segment", 1)])
                if segment_id is None or not fcai_seg:
                    continue

                carreb_label = self._safe_str(row[hmap.get("carreb_db_label", 2)])
                v_class = self._safe_str(row[hmap.get("vehicle_class", 3)])
                rep_veh = self._safe_str(row[hmap.get("representative_vehicles", 4)])
                criteria = self._safe_str(row[hmap.get("criteria_notes", 5)])
                source = self._safe_str(row[hmap.get("source", 6)])

                defaults = {
                    "fcai_segment": fcai_seg,
                    "carreb_db_label": carreb_label,
                    "vehicle_class": v_class,
                    "representative_vehicles": rep_veh,
                    "criteria_notes": criteria,
                    "source": source,
                }

                if not is_dry_run:
                    obj, created = FCAICategoryRegistry.objects.update_or_create(
                        segment_id=segment_id,
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
