from django.contrib import admin
from .models import Vehicle

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('brand', 'model', 'year', 'variant', 'powertrain_type', 'fcai_category')
    list_filter = ('brand', 'year', 'powertrain_type', 'body_style')
    search_fields = ('brand', 'model', 'variant')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Identity Information', {
            'fields': ('brand', 'model', 'year', 'variant', 'body_style', 'num_seats', 'powertrain_type', 'fcai_category', 'ancap_safety_rating')
        }),
        ('Emissions & Efficiency', {
            'fields': ('fuel_consumption_per_100km', 'electricity_consumption_per_100km', 'tailpipe_co2_g_per_km', 'wltp_range_km', 'test_cycle')
        }),
        ('Pricing & Costs', {
            'fields': ('driveaway_price_by_state', 'insurance_estimate_by_state', 'ctp_by_state', 'registration_by_state', 'servicing_5yr_estimate', 'tyre_replacement_estimate', 'resale_value_5yr_estimate')
        }),
        ('Metadata', {
            'fields': ('annual_km_default', 'provenance')
        }),
    )
