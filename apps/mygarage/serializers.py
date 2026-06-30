from rest_framework import serializers
from apps.mygarage.models import CurrentVehicle, GarageVehicle, VehicleOverride, UserPriorityState, GarageVehicleSource
from apps.vehicles.models import Vehicle

class CurrentVehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CurrentVehicle
        fields = ['id', 'vehicle_catalogue_id', 'manual_entry_data', 'purchase_date', 'licence_plate', 'odometer_reading', 'state', 'created_at', 'updated_at']

class GarageVehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = GarageVehicle
        fields = ['id', 'vehicle_catalogue_id', 'status', 'source', 'added_at', 'archived_at']

class VehicleOverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleOverride
        fields = ['id', 'field_name', 'override_value', 'overridden_at']

class UserPriorityStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPriorityState
        fields = ['budget_min', 'budget_max', 'priority_slider_position', 'active_core_mode', 'updated_at']
        read_only_fields = ['updated_at']

class CurrentVehicleCreateSerializer(serializers.Serializer):
    vehicle_catalogue_id = serializers.UUIDField(required=False, allow_null=True)
    manual_entry_data = serializers.JSONField(required=False, allow_null=True)
    purchase_date = serializers.DateField(required=False, allow_null=True)
    licence_plate = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    odometer_reading = serializers.IntegerField(required=False, allow_null=True)
    state = serializers.CharField(required=False, allow_blank=True, allow_null=True)

class GarageVehicleCreateSerializer(serializers.Serializer):
    vehicle_catalogue_id = serializers.UUIDField()
    source = serializers.ChoiceField(choices=GarageVehicleSource.choices)
    
class VehicleDetailOverrideSerializer(serializers.Serializer):
    field_name = serializers.CharField()
    override_value = serializers.JSONField()
