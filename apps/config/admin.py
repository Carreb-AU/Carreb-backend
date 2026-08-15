from django.contrib import admin
from .models import SiteConfig


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    """Expose SiteConfig as a singleton editable via Django admin."""

    fieldsets = (
        ('Identity', {
            'fields': ('site_name',),
        }),
        ('SEO & Canonicals', {
            'fields': ('default_meta_title', 'default_meta_description', 'canonical_host'),
        }),
        ('Analytics', {
            'fields': ('ga4_measurement_id',),
        }),
        ('Legal', {
            'fields': ('legal_effective_date',),
        }),
        ('Homepage Claims', {
            'fields': ('homepage_vehicle_count_claim',),
        }),
        ('Structured Data', {
            'fields': ('organization_json_ld',),
        }),
        ('Extra Head Tags', {
            'fields': ('extra_head_tags',),
            'classes': ('collapse',),
        }),
    )

    def has_add_permission(self, request):
        # Singleton: only one row allowed.
        if SiteConfig.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False
