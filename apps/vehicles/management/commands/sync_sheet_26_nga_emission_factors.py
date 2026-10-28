from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import NGAEmissionFactor


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 26 (NGA_EmissionFactors) into NGAEmissionFactor"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "NGA_EmissionFactors"
    source_code = "SYNC-SHEET-26-NGA-EMISSIONS"
    source_name = "National Greenhouse Accounts Scope-2 Electricity Emission Factors"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            NGAEmissionFactor.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                grid = self._safe_str(row[hmap.get("grid", 0)])
                if not grid:
                    continue
                if self._is_annotation_row(row, hmap, ["grid"], [
                    "states_covered", "scope2_factor_kgco2e_per_kwh", "edition",
                    "effective_period", "source", "devspec_ref",
                ]):
                    continue

                states = self._safe_str(row[hmap.get("states_covered", 1)])
                factor = self._safe_float(row[hmap.get("scope2_factor_kgco2e_per_kwh", 2)]) or 0.0
                edition = self._safe_str(row[hmap.get("edition", 3)])
                effective = self._safe_str(row[hmap.get("effective_period", 4)])
                source = self._safe_str(row[hmap.get("source", 5)])
                devspec = self._safe_str(row[hmap.get("devspec_ref", 6)])
                note = self._safe_str(row[hmap.get("note", 7)]) if len(row) > 7 else ""

                defaults = {
                    "states_covered": states,
                    "scope2_factor_kgco2e_per_kwh": factor,
                    "edition": edition,
                    "effective_period": effective,
                    "source": source,
                    "devspec_ref": devspec,
                    "note": note,
                }

                if not is_dry_run:
                    obj, created = NGAEmissionFactor.objects.update_or_create(
                        grid=grid,
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
