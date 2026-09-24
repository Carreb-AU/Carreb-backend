from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import Vehicle


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 7 (VehicleCOREScore_Canonical) into Vehicle mode_data_by_state canonical ratings"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "VehicleCOREScore_Canonical"
    source_code = "SYNC-SHEET-07-CORE-CANONICAL"
    source_name = "Canonical Pre-Calculated Vehicle CORE Scores"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        self.stdout.write(f"Processing {len(rows)-1} canonical score records...")

        # Process row by row and update Vehicle
        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                make = self._safe_str(row[hmap.get("make", 0)])
                model = self._safe_str(row[hmap.get("model", 1)])
                variant = self._safe_str(row[hmap.get("variant", 2)])
                year = self._safe_int(row[hmap.get("year", 3)]) or 2026
                mode = self._safe_str(row[hmap.get("core_mode", 7)]).upper()

                if not make or not model or not mode:
                    continue

                price_score = self._safe_float(self._row_val(row, hmap, "price_score"))
                emissions_score = self._safe_float(self._row_val(row, hmap, "emissions_score"))
                core_score = self._safe_float(self._row_val(row, hmap, "core_score"))
                stars = self._safe_float(self._row_val(row, hmap, "stars"))
                coo_pa = self._safe_float(self._row_val(row, hmap, "median_mode_coo_pa")) or self._safe_float(self._row_val(row, hmap, "coo_pa_canonical"))
                driveaway = self._safe_float(self._row_val(row, hmap, "median_driveaway"))

                if not is_dry_run:
                    v = Vehicle.objects.filter(
                        brand__iexact=make,
                        model__iexact=model,
                        variant__iexact=variant,
                        year=year,
                    ).first()

                    if v:
                        if not v.mode_data_by_state:
                            v.mode_data_by_state = {}
                        if "CANONICAL" not in v.mode_data_by_state:
                            v.mode_data_by_state["CANONICAL"] = {}

                        v.mode_data_by_state["CANONICAL"][mode] = {
                            "price_score": price_score,
                            "emissions_score": emissions_score,
                            "core_score": core_score,
                            "stars": stars,
                            "median_mode_coo_pa": coo_pa,
                            "median_driveaway": driveaway,
                        }
                        v.save(update_fields=["mode_data_by_state"])
                        updated_count += 1
                    else:
                        created_count += 1  # Vehicle pending from sheet 5
                else:
                    updated_count += 1

            except Exception as e:
                errors.append(f"Row {r_idx}: {e}")

        return created_count, updated_count, errors
