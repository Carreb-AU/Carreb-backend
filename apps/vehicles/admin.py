import os
from django.contrib import admin, messages
from django.conf import settings

from apps.vehicles.models import (
    Vehicle,
    DataSource,
    VehicleIdentity,
    CategoryCostDefault,
    CategoryScoringBounds,
    FinanceDefault,
    ManualVehicleEnrichment,
    EnergyTypeModifier,
    DepreciationBrandModifier,
    DepreciationLookup,
    FCAICategoryRegistry,
    StateEnergyPrice,
    CTPStateDefault,
    InsuranceCategoryBenchmark,
    InsuranceStateModifier,
    RegistrationCategoryBenchmark,
    RegistrationFeeByState,
    RegistrationStateFormula,
    MaintenanceCategoryDefault,
    TyreCategoryDefault,
    EnergyTypeCostModifier,
    CategoryAnnualKMBenchmark,
    StateAnnualKMBenchmark,
    COOBenchmarkAudit,
    VehicleCOOComponentBreakdown,
    NGAEmissionFactor,
    DriveawayTaxParameter,
    CoreDialBatch,
    CoreDialRow,
    ConsolidatedVehicleRow,
)
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
                f"GVG current: {results['gvg_current']['created']} created / {results['gvg_current']['updated']} updated / {results['gvg_current']['skipped']} skipped, "
                f"GVG older: {results['gvg_older']['created']} created / {results['gvg_older']['updated']} updated / {results['gvg_older']['skipped']} skipped.",
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


@admin.register(CategoryScoringBounds)
class CategoryScoringBoundsAdmin(admin.ModelAdmin):
    list_display = ["fcai_category", "core_mode", "vehicle_count", "cat_min_coo", "cat_max_coo", "cat_min_co2", "cat_max_co2", "scoring_version"]
    list_filter = ["core_mode", "scoring_version", "fcai_category"]
    search_fields = ["fcai_category"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(FinanceDefault)
class FinanceDefaultAdmin(admin.ModelAdmin):
    list_display = ["fcai_category_broad", "deposit_pct", "base_rate_pct", "alt_fuel_modifier_pct", "term_months", "effective_from", "updated_at"]
    search_fields = ["fcai_category_broad"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(EnergyTypeModifier)
class EnergyTypeModifierAdmin(admin.ModelAdmin):
    list_display = [
        "powertrain_type",
        "fuel_cost_multiplier",
        "electricity_cost_multiplier",
        "servicing_cost_multiplier",
        "tyre_cost_multiplier",
        "insurance_cost_multiplier",
        "registration_cost_multiplier",
        "resale_value_multiplier",
        "retention_multiplier",
        "updated_at",
    ]
    list_filter = ["powertrain_type"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(DepreciationBrandModifier)
class DepreciationBrandModifierAdmin(admin.ModelAdmin):
    list_display = ["brand", "retention_multiplier", "resale_value_multiplier", "updated_at"]
    search_fields = ["brand"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(DepreciationLookup)
class DepreciationLookupAdmin(admin.ModelAdmin):
    list_display = ["layer_num", "layer", "key", "powertrain_type", "modifier", "source", "updated_at"]
    list_filter = ["layer_num", "layer", "powertrain_type"]
    search_fields = ["layer", "key", "source"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(FCAICategoryRegistry)
class FCAICategoryRegistryAdmin(admin.ModelAdmin):
    list_display = ["segment_id", "fcai_segment", "carreb_db_label", "vehicle_class", "source", "updated_at"]
    list_filter = ["vehicle_class"]
    search_fields = ["fcai_segment", "carreb_db_label", "representative_vehicles", "criteria_notes"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(StateEnergyPrice)
class StateEnergyPriceAdmin(admin.ModelAdmin):
    list_display = ["state", "petrol_ulp95_cents_per_litre", "diesel_cents_per_litre", "electricity_cents_per_kwh", "data_period", "source", "updated_at"]
    search_fields = ["state", "data_period", "source"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(CTPStateDefault)
class CTPStateDefaultAdmin(admin.ModelAdmin):
    list_display = ["state", "annual_ctp_cents", "bundled_in_rego", "source", "updated_at"]
    search_fields = ["state", "bundled_in_rego", "source"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(InsuranceCategoryBenchmark)
class InsuranceCategoryBenchmarkAdmin(admin.ModelAdmin):
    list_display = ["fcai_category", "national_avg_cents_pa", "estimated_monthly_cents", "source", "updated_at"]
    search_fields = ["fcai_category", "representative_basis", "source"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(InsuranceStateModifier)
class InsuranceStateModifierAdmin(admin.ModelAdmin):
    list_display = ["state", "state_modifier", "relative_to_national", "avg_comprehensive_cents", "national_avg_cents", "source", "updated_at"]
    search_fields = ["state", "explanation", "source"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(RegistrationCategoryBenchmark)
class RegistrationCategoryBenchmarkAdmin(admin.ModelAdmin):
    list_display = ["fcai_category", "representative_vehicle", "kerb_weight_kg", "cylinders", "engine_l", "energy_type", "total_avg_cents_pa", "updated_at"]
    search_fields = ["fcai_category", "representative_vehicle"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(RegistrationFeeByState)
class RegistrationFeeByStateAdmin(admin.ModelAdmin):
    list_display = ["fcai_category", "state", "annual_fee_cents", "updated_at"]
    search_fields = ["fcai_category", "state"]
    list_filter = ["state", "fcai_category"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(RegistrationStateFormula)
class RegistrationStateFormulaAdmin(admin.ModelAdmin):
    list_display = ["state", "basis_notes", "updated_at"]
    search_fields = ["state", "basis_notes"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(MaintenanceCategoryDefault)
class MaintenanceCategoryDefaultAdmin(admin.ModelAdmin):
    list_display = ["fcai_category", "representative_vehicle", "service_interval", "five_year_total_cents", "annual_avg_cents", "source", "updated_at"]
    search_fields = ["fcai_category", "representative_vehicle", "source"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(TyreCategoryDefault)
class TyreCategoryDefaultAdmin(admin.ModelAdmin):
    list_display = ["fcai_category", "typical_tyre_size", "cost_per_set_4_cents", "replacement_interval_km", "annualised_cost_cents", "source", "updated_at"]
    search_fields = ["fcai_category", "typical_tyre_size", "source"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(EnergyTypeCostModifier)
class EnergyTypeCostModifierAdmin(admin.ModelAdmin):
    list_display = [
        "cost_component",
        "ice_petrol_str",
        "ice_diesel_str",
        "hev_hybrid_str",
        "bev_str",
        "phev_str",
        "confidence",
        "source",
        "updated_at",
    ]
    search_fields = ["cost_component", "rationale", "source"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(CategoryAnnualKMBenchmark)
class CategoryAnnualKMBenchmarkAdmin(admin.ModelAdmin):
    list_display = [
        "fcai_category",
        "est_annual_km",
        "abs_anchor",
        "vs_flat_17k",
        "confidence",
        "source",
        "updated_at",
    ]
    search_fields = ["fcai_category", "basis_pattern", "impact_on_coo", "source"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(StateAnnualKMBenchmark)
class StateAnnualKMBenchmarkAdmin(admin.ModelAdmin):
    list_display = [
        "state",
        "avg_km_per_vehicle",
        "vs_national",
        "source",
        "updated_at",
    ]
    search_fields = ["state", "source"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(COOBenchmarkAudit)
class COOBenchmarkAuditAdmin(admin.ModelAdmin):
    list_display = [
        "fcai_category",
        "usage_profile",
        "km_per_year_used",
        "nsw_coo_cents",
        "vic_coo_cents",
        "qld_coo_cents",
        "sa_coo_cents",
        "wa_coo_cents",
        "tas_coo_cents",
        "nt_coo_cents",
        "act_coo_cents",
        "updated_at",
    ]
    search_fields = ["fcai_category", "usage_profile", "notes"]
    list_filter = ["usage_profile"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(VehicleCOOComponentBreakdown)
class VehicleCOOComponentBreakdownAdmin(admin.ModelAdmin):
    list_display = [
        "make",
        "model",
        "variant",
        "year",
        "state",
        "fcai_category",
        "energy_norm",
        "km_pa_used",
        "components_sum_pa_cents",
        "base_coo_pa_canonical_cents",
        "updated_at",
    ]
    search_fields = ["make", "model", "variant", "fcai_category"]
    list_filter = ["state", "fcai_category", "energy_norm", "year"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(NGAEmissionFactor)
class NGAEmissionFactorAdmin(admin.ModelAdmin):
    list_display = [
        "grid",
        "states_covered",
        "scope2_factor_kgco2e_per_kwh",
        "edition",
        "effective_period",
        "devspec_ref",
        "updated_at",
    ]
    search_fields = ["grid", "states_covered", "edition", "note"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(DriveawayTaxParameter)
class DriveawayTaxParameterAdmin(admin.ModelAdmin):
    list_display = [
        "parameter",
        "value",
        "effective_from",
        "applies_to",
        "source",
        "devspec_ref",
        "updated_at",
    ]
    search_fields = ["parameter", "value", "applies_to", "source", "note"]
    readonly_fields = ["id", "created_at", "updated_at"]














class ManualVehicleEnrichmentInline(admin.StackedInline):
    model = ManualVehicleEnrichment
    extra = 0
    readonly_fields = ["id", "enriched_at", "updated_at"]


@admin.register(VehicleIdentity)
class VehicleIdentityAdmin(admin.ModelAdmin):
    list_display = ["make", "model", "year", "variant", "body_style", "powertrain_type", "fcai_category", "image_url", "tailpipe_co2_g_per_km", "source_dataset", "imported_at"]
    list_filter = ["source_dataset", "powertrain_type", "fcai_category", "year", "make"]
    search_fields = ["make", "model", "variant", "year"]
    readonly_fields = ["id", "imported_at", "updated_at"]
    inlines = [ManualVehicleEnrichmentInline]


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
    readonly_fields = ["id", "created_at", "updated_at", "image_classification"]
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
        ("Image Classification", {
            "classes": ("collapse",),
            "fields": ("image_classification",),
        }),
        ("Consolidated v6.4 — 21-Oct additions", {
            "classes": ("collapse",),
            "fields": (
                "transmission", "doors", "base_fuel",
                "phev_fuel_consumption_l100", "energy_consumption_wh_km",
                "co2_energy_cycle_basis", "maintenance_5yr_detail",
                "is_suppressed",
            ),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )


@admin.register(CoreDialBatch)
class CoreDialBatchAdmin(admin.ModelAdmin):
    list_display = ("scoring_version", "as_at", "is_current", "created_at", "row_count")
    list_filter = ("is_current",)
    search_fields = ("scoring_version",)
    ordering = ("-created_at",)

    @admin.display(description="Rows")
    def row_count(self, obj):
        return obj.rows.count()


@admin.register(CoreDialRow)
class CoreDialRowAdmin(admin.ModelAdmin):
    list_display = (
        "state", "version_id", "year", "make", "model", "variant",
        "driveaway_cents", "coo_pa_cents", "annual_co2_kg",
        "price_score", "emissions_score", "co2_cap", "bands_by_stop",
    )
    list_filter = ("state", "batch__scoring_version")
    search_fields = ("make", "model", "variant", "model_id")
    ordering = ("state", "version_id")
    list_per_page = 50
    autocomplete_fields = ("vehicle",)
    readonly_fields = ("bands_by_stop",)

    @admin.display(description="Band at stop 1→5")
    def bands_by_stop(self, obj):
        # Band is not stored — it is derived from the scores at query time.
        # Budget only filters the window; the stop weights decide the band.
        from apps.vehicles.services.core_dial import rate_version
        return " · ".join(
            str(rate_version(obj.price_score, obj.emissions_score, obj.co2_cap, stop)[1])
            for stop in range(1, 6)
        )


@admin.register(ConsolidatedVehicleRow)
class ConsolidatedVehicleRowAdmin(admin.ModelAdmin):
    list_display = (
        "listing_id", "state", "core_mode", "is_suppressed", "vehicle",
    )
    list_filter = ("state", "is_suppressed")
    search_fields = (
        "listing_id", "vehicle__brand", "vehicle__model", "vehicle__variant",
    )
    ordering = ("listing_id", "state", "core_mode")
    readonly_fields = ("id",)
