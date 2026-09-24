from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import VehicleIdentity, DataSource, ManualVehicleEnrichment, PowertrainType


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 1 (Data) from Market Gap-Fill Dataset into VehicleIdentity & DataSource"
    default_workbook_path = "Carreb - Market Gap-Fill Dataset TEMPLATE v1.0.xlsx"
    sheet_name = "Data"
    source_code = "SYNC-SHEET-01-GAPFILL"
    source_name = "Market Gap-Fill Dataset"

    POWERTRAIN_MAP = {
        "petrol": PowertrainType.PETROL,
        "diesel": PowertrainType.DIESEL,
        "hybrid": PowertrainType.HYBRID,
        "mild hybrid": PowertrainType.MILD_HYBRID,
        "plug-in hybrid": PowertrainType.PHEV,
        "phev": PowertrainType.PHEV,
        "electric": PowertrainType.BEV,
        "bev": PowertrainType.BEV,
        "hydrogen": PowertrainType.FCEV,
        "fcev": PowertrainType.FCEV,
    }

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        # Row 2 is headers, data rows start at index 3 (Row 4), Row 3 is worked example
        data_rows = [r for r in rows[3:] if any(c is not None and str(c).strip() != "" for c in r)]
        self.stdout.write(f"Found {len(data_rows)} user data rows in '{self.sheet_name}'")

        ds, _ = DataSource.objects.get_or_create(
            code="S-GAPFILL-TEMPLATE",
            defaults={"name": "Market Gap-Fill Ingestion Source", "dataset_type": "xlsx"}
        )

        for idx, row in enumerate(data_rows, start=4):
            try:
                make = self._safe_str(row[0])
                model = self._safe_str(row[1])
                variant = self._safe_str(row[2])
                year = self._safe_int(row[3]) or 2026

                if not make or not model:
                    continue

                fuel_raw = self._safe_str(row[5])
                ptype = self.POWERTRAIN_MAP.get(fuel_raw.lower(), PowertrainType.PETROL)
                on_sale_bool = True if self._safe_str(row[4]).lower() in ("yes", "runout") else False

                price_cents = self._dollars_to_cents(row[16]) if len(row) > 16 else None

                defaults = {
                    "source": ds,
                    "body_style": self._safe_str(row[11]) if len(row) > 11 else "",
                    "fcai_category": self._safe_str(row[10]) if len(row) > 10 else "",
                    "powertrain_type": ptype,
                    "fuel_type_raw": fuel_raw,
                    "engine_l": self._safe_float(row[6]),
                    "drive": self._safe_str(row[7]),
                    "battery_kwh": self._safe_float(row[8]) if len(row) > 8 else None,
                    "electric_range_km": self._safe_float(row[9]) if len(row) > 9 else None,
                    "num_seats": self._safe_int(row[12]) if len(row) > 12 else 5,
                    "transmission": self._safe_str(row[13]) if len(row) > 13 else "",
                    "tow_braked_kg": self._safe_int(row[14]) if len(row) > 14 else None,
                    "tow_unbraked_kg": self._safe_int(row[15]) if len(row) > 15 else None,
                    "driveaway_price_estimate": price_cents,
                    "price_type": self._safe_str(row[17]) if len(row) > 17 else "",
                    "price_state": self._safe_str(row[18]) if len(row) > 18 else "",
                    "price_as_at": self._parse_date(row[19]) if len(row) > 19 else None,
                    "fuel_consumption_combined_l_100km": self._safe_float(row[20]) if len(row) > 20 else None,
                    "fuel_consumption_urban_l_100km": self._safe_float(row[21]) if len(row) > 21 else None,
                    "fuel_consumption_extra_urban_l_100km": self._safe_float(row[22]) if len(row) > 22 else None,
                    "tailpipe_co2_g_per_km": self._safe_float(row[23]) if len(row) > 23 else None,
                    "is_current_model": on_sale_bool,
                    "sales_status": self._safe_str(row[4]),
                }

                if not is_dry_run:
                    obj, created = VehicleIdentity.objects.update_or_create(
                        make=make,
                        model=model,
                        variant=variant,
                        year=year,
                        defaults=defaults,
                    )
                    # Check ANCAP in ManualVehicleEnrichment
                    ancap_stars = self._safe_int(row[24]) if len(row) > 24 else None
                    ancap_year = self._safe_int(row[25]) if len(row) > 25 else None
                    if ancap_stars is not None or ancap_year is not None:
                        ManualVehicleEnrichment.objects.update_or_create(
                            record=obj,
                            defaults={
                                "ancap_safety_rating": ancap_stars,
                                "ancap_tested_year": ancap_year,
                                "enriched_by": "Gap-Fill Import",
                            }
                        )
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                else:
                    created_count += 1

            except Exception as e:
                errors.append(f"Row {idx}: {e}")

        return created_count, updated_count, errors
