from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import StateEnergyPrice


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 16 (FuelElectricityPrices) into StateEnergyPrice"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "FuelElectricityPrices"
    source_code = "SYNC-SHEET-16-ENERGY-PRICES"
    source_name = "State-by-State Fuel and Electricity Retail Prices"

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            StateEnergyPrice.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c).lower() for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        valid_states = {"NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT", "NATIONAL AVG"}

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                state_raw = self._safe_str(row[hmap.get("state", 0)])
                if not state_raw or state_raw.upper() not in valid_states:
                    continue

                state = state_raw if state_raw.lower() != "national avg" else "National Avg"

                petrol_val = self._safe_float(row[hmap.get("petrol_ulp95_per_litre", 1)])
                diesel_val = self._safe_float(row[hmap.get("diesel_per_litre", 2)])
                elec_val = self._safe_float(row[hmap.get("electricity_per_kwh", 3)])

                petrol_cents = int(round(petrol_val * 100)) if petrol_val is not None else None
                diesel_cents = int(round(diesel_val * 100)) if diesel_val is not None else None
                elec_cents = round(elec_val * 100, 2) if elec_val is not None else None

                data_period = self._safe_str(row[hmap.get("data_period", 4)]) if "data_period" in hmap else ""
                source = self._safe_str(row[hmap.get("source", 5)]) if "source" in hmap else ""

                defaults = {
                    "petrol_ulp95_cents_per_litre": petrol_cents,
                    "diesel_cents_per_litre": diesel_cents,
                    "electricity_cents_per_kwh": elec_cents,
                    "data_period": data_period,
                    "source": source,
                }

                if not is_dry_run:
                    obj, created = StateEnergyPrice.objects.update_or_create(
                        state=state,
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
