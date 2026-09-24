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


from .models import PlatformDefault, BuildChangelog, ReleaseSummaryMetric, ACLComplianceRule, SubstantiationSourceRegistry, PolicyUpdateLog, DevSpecTraceMap

@admin.register(PlatformDefault)
class PlatformDefaultAdmin(admin.ModelAdmin):
    list_display = ['config_key', 'config_value', 'config_type', 'source_label', 'last_updated']
    search_fields = ['config_key', 'description']
    list_filter = ['config_type']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(BuildChangelog)
class BuildChangelogAdmin(admin.ModelAdmin):
    list_display = ['order', 'item', 'prior_build', 'now_final', 'spec_source', 'updated_at']
    search_fields = ['item', 'prior_build', 'now_final', 'spec_source']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(ReleaseSummaryMetric)
class ReleaseSummaryMetricAdmin(admin.ModelAdmin):
    list_display = ['order', 'section', 'metric', 'value', 'updated_at']
    search_fields = ['section', 'metric', 'value']
    list_filter = ['section']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(ACLComplianceRule)
class ACLComplianceRuleAdmin(admin.ModelAdmin):
    list_display = ['order', 'rule_key', 'rule_text', 'updated_at']
    search_fields = ['rule_key', 'rule_text']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(SubstantiationSourceRegistry)
class SubstantiationSourceRegistryAdmin(admin.ModelAdmin):
    list_display = [
        'order',
        'data_category',
        'carreb_table_or_sheet',
        'primary_source',
        'refresh_cadence',
        'accc_substantiation_class',
        'updated_at',
    ]
    search_fields = ['data_category', 'carreb_table_or_sheet', 'primary_source', 'accc_substantiation_class']
    list_filter = ['refresh_cadence']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(PolicyUpdateLog)
class PolicyUpdateLogAdmin(admin.ModelAdmin):
    list_display = [
        'item_number',
        'parameter',
        'tab_affected',
        'old_value',
        'new_value',
        'effective_date',
        'status',
        'updated_at',
    ]
    search_fields = ['parameter', 'tab_affected', 'reason', 'source']
    list_filter = ['status', 'tab_affected']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(DevSpecTraceMap)
class DevSpecTraceMapAdmin(admin.ModelAdmin):
    list_display = [
        'item_number',
        'workbook_tab',
        'feeds',
        'dev_spec_section',
        'calc_spec_section',
        'source_of_truth',
        'updated_at',
    ]
    search_fields = ['workbook_tab', 'feeds', 'dev_spec_section', 'calc_spec_section', 'source_of_truth', 'notes']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['item_number']






