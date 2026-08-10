import os
from django.contrib import admin, messages
from django.conf import settings

from apps.vehicles.models import Vehicle, DataSource, GreenVehicleGuideRecord, CategoryCostDefault
from apps.vehicles.services.gvg_import import import_all


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "dataset_type", "is_active", "retrieved_at", "updated_at"]
    list_filter = ["dataset_type", "is_active"]
    search_fields = ["code", "name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    actions = ["import_gvg_data_from_docs"]

    @admin.action(description="Import GVG data from docs/ folder")
    def import_gvg_data_from_docs(self, request, queryset):
        base_dir = settings.BASE_DIR
        workbook = os.path.join(base_dir, "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx")
        gvg_xlsx = os.path.join(base_dir, "docs", "GVG-Vehicles-2004-2025.xlsx")
        old_csv = os.path.join(base_dir, "docs", "FuelConsumptionGuide1986-2003.csv")

        missing = [p for p in [workbook, gvg_xlsx, old_csv] if not os.path.exists(p)]
        if missing:
            self.message_user(request, f"Missing files: {missing}", level=messages.ERROR)
            return

        try:
            results = import_all(workbook, gvg_xlsx, old_csv, clear=False)
            self.message_user(
                request,
                f"Imported. Category defaults: {results['category_defaults']}, "
                f"GVG current: {results['gvg_current']['created']} created / {results['gvg_current']['skipped']} skipped, "
                f"GVG older: {results['gvg_older']['created']} created / {results['gvg_older']['skipped']} skipped.",
                level=messages.SUCCESS,
            )
        except Exception as e:
            self.message_user(request, f"Import failed: {e}", level=messages.ERROR)


@admin.register(CategoryCostDefault)
class CategoryCostDefaultAdmin(admin.ModelAdmin):
    list_display = ["fcai_category", "state", "annual_km", "ctp_pa", "comprehensive_pa", "registration_pa", "updated_at"]
    list_filter = ["fcai_category", "state"]
    search_fields = ["fcai_category", "fcai_broad"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(GreenVehicleGuideRecord)
class GreenVehicleGuideRecordAdmin(admin.ModelAdmin):
    list_display = ["make", "model", "year", "variant", "body_style", "powertrain_type", "fcai_category", "tailpipe_co2_g_per_km", "source_dataset", "imported_at"]
    list_filter = ["source_dataset", "powertrain_type", "fcai_category", "year", "make"]
    search_fields = ["make", "model", "variant", "year"]
    readonly_fields = ["id", "imported_at", "updated_at"]


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = [
        "brand",
        "model",
        "year",
        "variant",
        "powertrain_type",
        "body_style",
        "fcai_category",
        "num_seats",
        "ancap_safety_rating",
        "tailpipe_co2_g_per_km",
        "updated_at",
    ]
    list_filter = [
        "powertrain_type",
        "body_style",
        "year",
        "brand",
        "fcai_category",
        "ancap_safety_rating",
        "test_cycle",
        "is_scoring_outlier",
    ]
    search_fields = ["brand", "model", "variant", "fcai_category"]
    ordering = ["brand", "model", "year", "variant"]
    readonly_fields = ["id", "created_at", "updated_at"]
    date_hierarchy = "created_at"

    fieldsets = (
        ("Identity", {
            "fields": (
                "id",
                "brand", "model", "year", "variant",
                "body_style", "num_seats",
                "powertrain_type", "fcai_category", "fcai_broad",
                "ancap_safety_rating", "is_scoring_outlier", "scoring_version",
            ),
        }),
        ("Emissions, Efficiency & Specs", {
            "fields": (
                "engine_l", "battery_kwh", "drive", "energy_norm",
                "fuel_consumption_per_100km",
                "electricity_consumption_per_100km",
                "tailpipe_co2_g_per_km",
                "wltp_range_km",
                "test_cycle",
                "annual_km_default",
            ),
        }),
        ("Pricing by State (cents)", {
            "fields": (
                "driveaway_price_by_state",
                "total_5yr_cost_of_ownership_by_state",
            ),
        }),
        ("Running Costs by State (cents)", {
            "classes": ("collapse",),
            "fields": (
                "insurance_estimate_by_state",
                "ctp_by_state",
                "registration_by_state",
                "fuel_cost_by_state",
                "electricity_cost_by_state",
                "ev_levy_by_state",
                "base_coo_by_state",
                "components_sum_by_state",
            ),
        }),
        ("Advanced Mode Data by State", {
            "classes": ("collapse",),
            "fields": (
                "mode_data_by_state",
            ),
        }),
        ("5-Year Cost Estimates (cents)", {
            "fields": (
                "servicing_5yr_estimate",
                "tyre_replacement_estimate",
                "resale_value_5yr_estimate",
            ),
        }),
        ("Provenance", {
            "classes": ("collapse",),
            "fields": ("provenance",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )
