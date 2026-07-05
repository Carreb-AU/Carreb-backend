from django.contrib import admin
from django.utils.html import format_html

from apps.freematch.models import FreeMatchSession


@admin.register(FreeMatchSession)
class FreeMatchSessionAdmin(admin.ModelAdmin):
    list_display = [
        "token_preview",
        "has_current_vehicle",
        "fuel_type_preference",
        "primary_use",
        "annual_km",
        "matched_vehicle",
        "converted_user",
        "created_at",
        "expires_at",
        "status_badge",
    ]
    list_filter = [
        "has_current_vehicle",
        "fuel_type_preference",
        "primary_use",
    ]
    readonly_fields = [
        "id",
        "session_token",
        "created_at",
        "expires_at",
    ]
    search_fields = [
        "session_token",
        "current_vehicle_make",
        "current_vehicle_model",
        "converted_user__email",
        "matched_vehicle__brand",
        "matched_vehicle__model",
    ]
    raw_id_fields = ["matched_vehicle", "converted_user"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    fieldsets = (
        ("Session", {
            "fields": ("id", "session_token", "created_at", "expires_at"),
        }),
        ("Step 1 — Current Vehicle?", {
            "fields": ("has_current_vehicle",),
        }),
        ("Step 2 — Current Vehicle Details", {
            "classes": ("collapse",),
            "fields": ("current_vehicle_make", "current_vehicle_model", "current_vehicle_year"),
        }),
        ("Step 3 — Preferences", {
            "fields": ("fuel_type_preference", "annual_km", "primary_use"),
        }),
        ("Match & Conversion", {
            "fields": ("matched_vehicle", "converted_user"),
        }),
    )

    @admin.display(description="Token")
    def token_preview(self, obj):
        return f"{obj.session_token[:14]}…"

    @admin.display(description="Status")
    def status_badge(self, obj):
        if obj.converted_user_id:
            return format_html('<span style="color:#16a34a;font-weight:bold;">✓ Converted</span>')
        if obj.is_expired:
            return format_html('<span style="color:#9ca3af;">Expired</span>')
        if obj.matched_vehicle_id:
            return format_html('<span style="color:#2563eb;">Matched</span>')
        return format_html('<span style="color:#d97706;">In Progress</span>')
