from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import EnergyTypeCostModifier


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 21 (EnergyTypeCostModifiers) into EnergyTypeCostModifier"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "EnergyTypeCostModifiers"
    source_code = "SYNC-SHEET-21-ENERGY-MODIFIERS"
    source_name = "Energy and Powertrain Cost Component Modifiers"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            EnergyTypeCostModifier.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                comp = self._safe_str(row[hmap.get("cost_component", 0)])
                if not comp:
                    continue
                if self._is_annotation_row(row, hmap, ["cost_component"], [
                    "ice_petrol", "ice_diesel", "hev_hybrid", "bev", "phev",
                    "rationale", "confidence",
                ]):
                    continue

                ice_petrol_val = row[hmap.get("ice_petrol", 1)]
                ice_diesel_val = row[hmap.get("ice_diesel", 2)]
                hev_val = row[hmap.get("hev_hybrid", 3)]
                bev_val = row[hmap.get("bev", 4)]
                phev_val = row[hmap.get("phev", 5)]

                rationale = self._safe_str(row[hmap.get("rationale", 6)])
                confidence = self._safe_str(row[hmap.get("confidence", 7)])

                defaults = {
                    "ice_petrol_str": self._safe_str(ice_petrol_val),
                    "ice_diesel_str": self._safe_str(ice_diesel_val),
                    "hev_hybrid_str": self._safe_str(hev_val),
                    "bev_str": self._safe_str(bev_val),
                    "phev_str": self._safe_str(phev_val),
                    "ice_petrol_multiplier": self._safe_float(ice_petrol_val),
                    "ice_diesel_multiplier": self._safe_float(ice_diesel_val),
                    "hev_hybrid_multiplier": self._safe_float(hev_val),
                    "bev_multiplier": self._safe_float(bev_val),
                    "phev_multiplier": self._safe_float(phev_val),
                    "rationale": rationale,
                    "confidence": confidence,
                }

                if not is_dry_run:
                    obj, created = EnergyTypeCostModifier.objects.update_or_create(
                        cost_component=comp,
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
