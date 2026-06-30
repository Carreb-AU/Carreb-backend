from django.contrib import admin
from .models import CurrentVehicle, GarageVehicle, VehicleOverride, UserPriorityState

@admin.register(CurrentVehicle)
class CurrentVehicleAdmin(admin.ModelAdmin):
    list_display = ('user', 'vehicle_catalogue', 'licence_plate', 'state', 'created_at')
    search_fields = ('user__email', 'licence_plate')
    list_filter = ('state',)

@admin.register(GarageVehicle)
class GarageVehicleAdmin(admin.ModelAdmin):
    list_display = ('user', 'vehicle_catalogue', 'status', 'source', 'added_at')
    search_fields = ('user__email', 'vehicle_catalogue__model')
    list_filter = ('status', 'source')

@admin.register(VehicleOverride)
class VehicleOverrideAdmin(admin.ModelAdmin):
    list_display = ('user', 'field_name', 'current_vehicle', 'garage_vehicle', 'overridden_at')
    search_fields = ('user__email', 'field_name')

@admin.register(UserPriorityState)
class UserPriorityStateAdmin(admin.ModelAdmin):
    list_display = ('user', 'active_core_mode', 'priority_slider_position', 'updated_at')
    search_fields = ('user__email',)
    list_filter = ('active_core_mode',)
