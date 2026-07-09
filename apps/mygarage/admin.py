from django.contrib import admin

from apps.mygarage.models import (
    CurrentVehicle,
    GarageVehicle,
    GarageVehicleStatus,
    VehicleOverride,
    UserPriorityState,
    RideRevealCredit,
    RideRevealResult,
    RideRevealJob,
    AISmartMatchRequest,
    DealerSearchLog,
)


@admin.register(CurrentVehicle)
class CurrentVehicleAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "vehicle_catalogue",
        "state",
        "odometer_reading",
        "purchase_date",
        "created_at",
        "updated_at",
    ]
    search_fields = [
        "user__email",
        "user__first_name",
        "user__last_name",
        "vehicle_catalogue__brand",
        "vehicle_catalogue__model",
        "licence_plate",
    ]
    list_filter = ["state"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["user", "vehicle_catalogue"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    fieldsets = (
        ("Owner", {
            "fields": ("id", "user"),
        }),
        ("Vehicle", {
            "fields": ("vehicle_catalogue", "manual_entry_data"),
        }),
        ("Details", {
            "fields": ("purchase_date", "licence_plate", "odometer_reading", "state"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )


@admin.register(GarageVehicle)
class GarageVehicleAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "vehicle_catalogue",
        "status",
        "source",
        "added_at",
        "archived_at",
    ]
    search_fields = [
        "user__email",
        "user__first_name",
        "user__last_name",
        "vehicle_catalogue__brand",
        "vehicle_catalogue__model",
    ]
    list_filter = ["status", "source"]
    readonly_fields = ["id", "added_at", "archived_at"]
    raw_id_fields = ["user", "vehicle_catalogue"]
    date_hierarchy = "added_at"
    ordering = ["-added_at"]

    fieldsets = (
        ("Owner & Vehicle", {
            "fields": ("id", "user", "vehicle_catalogue"),
        }),
        ("Status", {
            "fields": ("status", "source", "added_at", "archived_at"),
        }),
    )

    actions = ["mark_archived", "mark_active"]

    @admin.action(description="Archive selected garage vehicles")
    def mark_archived(self, request, queryset):
        from django.utils import timezone
        queryset.update(status=GarageVehicleStatus.ARCHIVED, archived_at=timezone.now())

    @admin.action(description="Re-activate selected garage vehicles")
    def mark_active(self, request, queryset):
        queryset.update(status=GarageVehicleStatus.ACTIVE, archived_at=None)


@admin.register(VehicleOverride)
class VehicleOverrideAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "field_name",
        "override_value",
        "current_vehicle",
        "garage_vehicle",
        "overridden_at",
    ]
    search_fields = [
        "user__email",
        "field_name",
    ]
    list_filter = ["field_name"]
    readonly_fields = ["id", "overridden_at"]
    raw_id_fields = ["user", "current_vehicle", "garage_vehicle"]
    ordering = ["-overridden_at"]

    fieldsets = (
        ("Owner", {
            "fields": ("id", "user"),
        }),
        ("Target Vehicle", {
            "fields": ("current_vehicle", "garage_vehicle"),
        }),
        ("Override", {
            "fields": ("field_name", "override_value", "overridden_at"),
        }),
    )


@admin.register(UserPriorityState)
class UserPriorityStateAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "active_core_mode",
        "priority_slider_position",
        "budget_min",
        "budget_max",
        "updated_at",
    ]
    search_fields = ["user__email", "user__first_name", "user__last_name"]
    list_filter = ["active_core_mode", "priority_slider_position"]
    readonly_fields = ["id", "updated_at"]
    raw_id_fields = ["user"]
    ordering = ["-updated_at"]

    fieldsets = (
        ("Owner", {
            "fields": ("id", "user"),
        }),
        ("CORE Settings", {
            "fields": ("active_core_mode", "priority_slider_position"),
        }),
        ("Budget", {
            "fields": ("budget_min", "budget_max"),
        }),
        ("Timestamps", {
            "fields": ("updated_at",),
        }),
    )

@admin.register(RideRevealCredit)
class RideRevealCreditAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "plan",
        "credits_included",
        "credits_purchased",
        "credits_used",
        "credits_available",
        "period_start",
        "period_end",
        "updated_at",
    ]
    search_fields = ["user__email"]
    list_filter = ["plan"]
    readonly_fields = ["id", "credits_available", "updated_at"]
    raw_id_fields = ["user"]

@admin.register(RideRevealResult)
class RideRevealResultAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "garage_vehicle",
        "archetype_name",
        "credit_type",
        "generated_at",
    ]
    search_fields = ["user__email", "archetype_name", "garage_vehicle__vehicle_catalogue__brand"]
    list_filter = ["credit_type", "ai_model_version"]
    readonly_fields = ["id", "generated_at", "generation_duration_ms"]
    raw_id_fields = ["user", "garage_vehicle", "vehicle_catalogue"]
    date_hierarchy = "generated_at"

@admin.register(RideRevealJob)
class RideRevealJobAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "garage_vehicle",
        "status",
        "created_at",
        "completed_at",
    ]
    search_fields = ["user__email", "id"]
    list_filter = ["status"]
    readonly_fields = ["id", "created_at", "completed_at", "error_message"]
    raw_id_fields = ["user", "garage_vehicle", "result"]
    date_hierarchy = "created_at"


@admin.register(AISmartMatchRequest)
class AISmartMatchRequestAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "raw_query",
        "result_count",
        "ai_service_available",
        "match_count_at_time",
        "created_at",
    ]
    search_fields = ["user__email", "raw_query"]
    list_filter = ["ai_service_available"]
    readonly_fields = ["id", "created_at"]
    raw_id_fields = ["user"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]


@admin.register(DealerSearchLog)
class DealerSearchLogAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "vehicle_brand",
        "postcode",
        "radius_km",
        "results_count",
        "created_at",
    ]
    search_fields = ["user__email", "vehicle_brand", "postcode"]
    list_filter = ["radius_km"]
    readonly_fields = ["id", "created_at"]
    raw_id_fields = ["user"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]
