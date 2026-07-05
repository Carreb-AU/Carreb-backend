from django.contrib import admin

from apps.prelaunch.models import WaitlistEntry, PrelaunchConfig


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ["email", "source", "submitted_at", "notified_at"]
    search_fields = ["email"]
    list_filter = ["source", "notified_at"]
    ordering = ["-submitted_at"]
    date_hierarchy = "submitted_at"
    readonly_fields = ["submitted_at"]

    fieldsets = (
        ("Contact", {
            "fields": ("email", "source"),
        }),
        ("Status", {
            "fields": ("submitted_at", "notified_at"),
        }),
    )

    actions = ["mark_notified"]

    @admin.action(description="Mark selected entries as notified (now)")
    def mark_notified(self, request, queryset):
        from django.utils import timezone
        queryset.filter(notified_at__isnull=True).update(notified_at=timezone.now())
        self.message_user(request, "Selected entries marked as notified.")


@admin.register(PrelaunchConfig)
class PrelaunchConfigAdmin(admin.ModelAdmin):
    list_display = ["launch_date"]
    readonly_fields = []

    fieldsets = (
        ("Launch Settings", {
            "description": "There can only be one configuration record.",
            "fields": ("launch_date",),
        }),
    )

    def has_add_permission(self, request):
        # Only allow one record to exist
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False
