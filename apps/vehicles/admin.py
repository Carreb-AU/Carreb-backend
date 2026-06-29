from django.contrib import admin
from .models import Vehicle, VehicleCoreRating

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('model_name', 'year', 'body_type', 'engine_type', 'transmission', 'is_active')
    list_filter = ('body_type', 'engine_type', 'transmission', 'is_active')
    search_fields = ('model_name', 'description')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('model_name', 'year', 'body_type', 'engine_type', 'transmission', 'trim_level', 'body_style', 'drive_type', 'fuel_type')
        }),
        ('Performance', {
            'fields': ('displacement', 'horsepower', 'torque', 'acceleration', 'top_speed', 'fuel_economy_city', 'fuel_economy_highway')
        }),
        ('Dimensions', {
            'fields': ('length', 'width', 'height', 'wheelbase', 'ground_clearance', 'cargo_volume', 'passenger_capacity')
        }),
        ('Features', {
            'fields': ('safety_rating', 'infotainment_features', 'comfort_features', 'connectivity_features')
        }),
        ('Pricing', {
            'fields': ('msrp', 'invoice_price', 'estimated_dealer_cost', 'resale_value', 'depreciation_rate')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )

@admin.register(VehicleCoreRating)
class VehicleCoreRatingAdmin(admin.ModelAdmin):
    list_display = ('vehicle', 'safety_score', 'reliability_score', 'performance_score', 'efficiency_score', 'comfort_score', 'value_score', 'overall_score', 'calculated_at')
    list_filter = ('calculated_at',)
    search_fields = ('vehicle__model_name',)
    readonly_fields = ('calculated_at',)
    ordering = ('-calculated_at',)
