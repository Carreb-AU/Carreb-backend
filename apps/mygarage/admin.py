from django.contrib import admin

from apps.mygarage.models import (
    CurrentVehicle,
    GarageVehicle,
    GarageVehicleStatus,
    VehicleOverride,
    UserPriorityState,
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
