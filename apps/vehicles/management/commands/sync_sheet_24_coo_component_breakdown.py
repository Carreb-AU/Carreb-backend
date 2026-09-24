from typing import List, Tuple
from apps.vehicles.management.commands.base_sync import BaseSheetSyncCommand
from apps.vehicles.models import Vehicle, VehicleCOOComponentBreakdown


class Command(BaseSheetSyncCommand):
    help = "Sync Sheet 24 (COO_Component_Breakdown) into VehicleCOOComponentBreakdown model"
    default_workbook_path = "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx"
    sheet_name = "COO_Component_Breakdown"
    source_code = "SYNC-SHEET-24-COO-BREAKDOWN"
    source_name = "Granular Vehicle COO Component Breakdown by State"

    _JUNK_KEYWORDS = ("SOURCES & METHODOLOGY", "component", "primary_source", "_", "section")

    def sync_sheet(self, sheet, is_dry_run: bool = False, clear: bool = False) -> Tuple[int, int, List[str]]:
        created_count, updated_count, errors = 0, 0, []
        if clear and not is_dry_run:
            VehicleCOOComponentBreakdown.objects.all().delete()

        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 2:
            return 0, 0, ["Sheet has insufficient rows."]

        headers = [self._safe_str(c) for c in rows[0]]
        hmap = {h: idx for idx, h in enumerate(headers) if h}

        self.stdout.write(f"Ingesting {len(rows)-1} rows into VehicleCOOComponentBreakdown...")

        for r_idx, row in enumerate(rows[1:], start=2):
            try:
                make = self._safe_str(row[hmap.get("Make", 0)])
                if not make or any(kw in make for kw in self._JUNK_KEYWORDS):
                    continue

                model = self._safe_str(row[hmap.get("Model", 1)])
                variant = self._safe_str(row[hmap.get("Variant", 2)])
                year = self._safe_int(row[hmap.get("Year", 3)]) or 2026
                state = self._safe_str(row[hmap.get("State", 4)]).upper()

                if not model or not state:
                    continue

                fcai_cat = self._safe_str(row[hmap.get("fcai_category", 5)])
                fcai_broad = self._safe_str(row[hmap.get("fcai_broad", 6)])
                energy_norm = self._safe_str(row[hmap.get("energy_norm", 7)])
                km_pa = self._safe_int(row[hmap.get("km_pa_used", 8)]) or 13300

                # Monetary conversions to integer cents
                fuel_cents = self._dollars_to_cents(row[hmap.get("fuel_cost_pa")]) or 0
                elec_cents = self._dollars_to_cents(row[hmap.get("electricity_cost_pa")]) or 0
                ctp_cents = self._dollars_to_cents(row[hmap.get("ctp_pa")]) or 0
                comp_cents = self._dollars_to_cents(row[hmap.get("comprehensive_pa")]) or 0
                rego_cents = self._dollars_to_cents(row[hmap.get("registration_pa")]) or 0
                maint_cents = self._dollars_to_cents(row[hmap.get("maintenance_pa")]) or 0
                tyre_cents = self._dollars_to_cents(row[hmap.get("tyre_cost_pa")]) or 0
                ev_levy_cents = self._dollars_to_cents(row[hmap.get("ev_levy_pa")]) or 0
                comp_sum_cents = self._dollars_to_cents(row[hmap.get("components_sum_pa")]) or 0
                base_coo_cents = self._dollars_to_cents(row[hmap.get("base_coo_pa_canonical")]) or 0
                delta_cents = self._dollars_to_cents(row[hmap.get("delta_components_vs_canonical")]) or 0

                scaling_factor = self._safe_float(row[hmap.get("scaling_factor_to_canonical")])
                scoring_ver = self._safe_str(row[hmap.get("scoring_version")]) or "v6.3.4-cat-norm"

                # Attempt link to Vehicle if it exists
                vehicle_obj = None
                if not is_dry_run:
                    vehicle_obj = Vehicle.objects.filter(
                        brand__iexact=make,
                        model__iexact=model,
                        variant__iexact=variant,
                        year=year,
                    ).first()

                defaults = {
                    "vehicle": vehicle_obj,
                    "fcai_category": fcai_cat,
                    "fcai_broad": fcai_broad,
                    "energy_norm": energy_norm,
                    "km_pa_used": km_pa,
                    "fuel_cost_pa_cents": fuel_cents,
                    "electricity_cost_pa_cents": elec_cents,
                    "ctp_pa_cents": ctp_cents,
                    "comprehensive_pa_cents": comp_cents,
                    "registration_pa_cents": rego_cents,
                    "maintenance_pa_cents": maint_cents,
                    "tyre_cost_pa_cents": tyre_cents,
                    "ev_levy_pa_cents": ev_levy_cents,
                    "components_sum_pa_cents": comp_sum_cents,
                    "base_coo_pa_canonical_cents": base_coo_cents,
                    "delta_components_vs_canonical_cents": delta_cents,
                    "scaling_factor_to_canonical": scaling_factor,
                    "scoring_version": scoring_ver,
                }

                if not is_dry_run:
                    obj, created = VehicleCOOComponentBreakdown.objects.update_or_create(
                        make=make,
                        model=model,
                        variant=variant,
                        year=year,
                        state=state,
                        defaults=defaults,
                    )
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                else:
                    created_count += 1

                if r_idx % 1000 == 0:
                    self.stdout.write(f"Processed {r_idx} breakdown rows...")

            except Exception as e:
                errors.append(f"Row {r_idx}: {e}")

        return created_count, updated_count, errors
