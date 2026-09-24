from collections import defaultdict
from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import Vehicle, PowertrainType, TestCycle


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 5 (v6.3.4 Data) from Carreb Calc Workbook v6.4 into Vehicle model"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "v6.3.4 Data"
    source_code = "SYNC-SHEET-05-V634-DATA"
    source_name = "Carreb v6.3.4 Vehicle Multi-Mode Dataset"

    _JUNK_KEYWORDS = (
        "_", "section", "computed", "internal", "primary_source",
        "insurancedefaults", "energytypecostmodifiers", "registrationdefaults",
        "scaling_factor",
    )

    def _is_junk_make(self, make: str) -> bool:
        if not make:
            return True
        t = make.strip().lower()
        return any(kw in t for kw in self._JUNK_KEYWORDS)

    def _map_powertrain(self, fuel_type: str) -> str:
        if not fuel_type:
            return PowertrainType.PETROL
        ft = fuel_type.strip().lower()
        if "mild" in ft:
            return PowertrainType.MILD_HYBRID
        if "phev" in ft or "plug-in" in ft:
            return PowertrainType.PHEV
        if "hev" in ft or "hybrid" in ft:
            return PowertrainType.HYBRID
        if "bev" in ft or "electric" in ft:
            return PowertrainType.BEV
        if "diesel" in ft:
            return PowertrainType.DIESEL
        if "fcev" in ft or "hydrogen" in ft:
            return PowertrainType.FCEV
        return PowertrainType.PETROL

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            self.stdout.write(self.style.WARNING("Clearing existing Vehicle records (--clear specified)..."))
            Vehicle.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c) for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        # Group data rows by (make, model, variant, year)
        vehicles_dict = defaultdict(list)
        for r_idx, row in enumerate(rows[1:], start=2):
            make = self._safe_str(row[hmap.get("Make", 0)])
            if self._is_junk_make(make):
                continue
            model = self._safe_str(row[hmap.get("Model", 1)])
            variant = self._safe_str(row[hmap.get("Variant", 2)])
            year = self._safe_int(row[hmap.get("Year", 3)]) or 2026

            key = (make, model, variant, year)
            vehicles_dict[key].append(row)

        self.stdout.write(f"Aggregated {len(rows)-1} rows into {len(vehicles_dict)} distinct vehicles.")

        for (make, model, variant, year), row_list in vehicles_dict.items():
            try:
                base_row = row_list[0]
                driveaway_by_state = {}
                coo_5yr_by_state = {}
                mode_data_by_state = {}

                for r in row_list:
                    state = self._safe_str(r[hmap["State"]]).upper() if "State" in hmap else ""
                    mode = self._safe_str(r[hmap["CORE Mode"]]).upper() if "CORE Mode" in hmap else ""
                    if not state:
                        continue

                    # Store driveaway price in cents
                    if "Driveaway Price ($)" in hmap and state not in driveaway_by_state:
                        price_cents = self._dollars_to_cents(r[hmap["Driveaway Price ($)"]])
                        if price_cents is not None:
                            driveaway_by_state[state] = price_cents

                    # Store 5yr COO in cents
                    if "Mode 5yr COO ($)" in hmap:
                        coo_cents = self._dollars_to_cents(r[hmap["Mode 5yr COO ($)"]])
                        if mode == "CASH" or state not in coo_5yr_by_state:
                            coo_5yr_by_state[state] = coo_cents

                    # Store mode data
                    if state not in mode_data_by_state:
                        mode_data_by_state[state] = {}

                    if mode:
                        mode_data_by_state[state][mode] = {
                            "finance_cost_pa": self._safe_float(self._row_val(r, hmap, "Finance Cost p.a. ($)")),
                            "resale_credit_pa": self._safe_float(self._row_val(r, hmap, "Resale Credit p.a. ($)")),
                            "mode_coo_pa": self._safe_float(self._row_val(r, hmap, "Mode COO p.a. ($)")),
                            "mode_5yr_coo": self._safe_float(self._row_val(r, hmap, "Mode 5yr COO ($)")),
                            "annual_co2_kg": self._safe_float(self._row_val(r, hmap, "Annual CO2 (kg)")),
                            "price_score": self._safe_float(self._row_val(r, hmap, "price_score")),
                            "emissions_score": self._safe_float(self._row_val(r, hmap, "emissions_score")),
                            "core_score": self._safe_float(self._row_val(r, hmap, "core_score")),
                            "stars": self._safe_float(self._row_val(r, hmap, "stars")),
                            "mode_label": self._safe_str(self._row_val(r, hmap, "Mode Label")),
                        }

                fuel_eff = self._safe_float(self._row_val(base_row, hmap, "Fuel Eff (L/100km)"))
                co2 = self._safe_float(self._row_val(base_row, hmap, "CO2 Tailpipe (g/km)"))
                range_km = self._safe_float(self._row_val(base_row, hmap, "Range (km)"))
                battery = self._safe_float(self._row_val(base_row, hmap, "Battery (kWh)"))
                fuel_type = self._safe_str(self._row_val(base_row, hmap, "Fuel Type"))
                body_type = self._safe_str(self._row_val(base_row, hmap, "Body Type"))
                engine_l = self._safe_float(self._row_val(base_row, hmap, "Engine (L)"))
                drive = self._safe_str(self._row_val(base_row, hmap, "Drive"))
                is_outlier = self._safe_bool(self._row_val(base_row, hmap, "is_scoring_outlier"))
                scoring_ver = self._safe_str(self._row_val(base_row, hmap, "scoring_version"))
                img_url = self._safe_str(self._row_val(base_row, hmap, "Image url ")) or self._safe_str(self._row_val(base_row, hmap, "Image url"))

                defaults = {
                    "body_style": body_type,
                    "image_url": img_url if img_url else None,
                    "powertrain_type": self._map_powertrain(fuel_type),
                    "fcai_category": self._safe_str(self._row_val(base_row, hmap, "fcai_category")),
                    "fcai_broad": self._safe_str(self._row_val(base_row, hmap, "fcai_broad")),
                    "energy_norm": self._safe_str(self._row_val(base_row, hmap, "Energy (norm)")),
                    "drive": drive,
                    "engine_l": engine_l,
                    "battery_kwh": battery,
                    "is_scoring_outlier": is_outlier,
                    "scoring_version": scoring_ver,
                    "driveaway_price_by_state": driveaway_by_state,
                    "fuel_consumption_per_100km": fuel_eff,
                    "tailpipe_co2_g_per_km": co2,
                    "wltp_range_km": range_km,
                    "test_cycle": TestCycle.ADR,
                    "total_5yr_cost_of_ownership_by_state": coo_5yr_by_state,
                    "mode_data_by_state": mode_data_by_state,
                }

                if not is_dry_run:
                    v, created = Vehicle.objects.update_or_create(
                        brand=make,
                        model=model,
                        variant=variant,
                        year=year,
                        defaults=defaults,
                    )
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                else:
                    created_count += 1

            except Exception as e:
                errors.append(f"{make} {model} {variant}: {e}")

        return created_count, updated_count, errors
