from rest_framework import serializers
from apps.mygarage.models import CurrentVehicle, GarageVehicle, VehicleOverride, UserPriorityState, GarageVehicleSource
from apps.vehicles.models import Vehicle, AustralianState
from apps.vehicles.services.core_dial import (
    BUDGET_MAX_DOLLARS,
    BUDGET_MIN_DOLLARS,
    BUDGET_STEP_DOLLARS,
    PRIORITY_STOPS,
)

class CurrentVehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CurrentVehicle
        fields = ['id', 'vehicle_catalogue_id', 'green_vehicle_guide_record_id', 'manual_entry_data', 'purchase_date', 'licence_plate', 'odometer_reading', 'state', 'created_at', 'updated_at']

class GarageVehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = GarageVehicle
        fields = ['id', 'vehicle_catalogue_id', 'status', 'source', 'added_at', 'archived_at']

class VehicleOverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleOverride
        fields = ['id', 'field_name', 'override_value', 'overridden_at']

class StateChoiceField(serializers.ChoiceField):
    """Choice field for the eight state codes; accepts any case."""
    def to_internal_value(self, data):
        if isinstance(data, str):
            data = data.upper()
        return super().to_internal_value(data)


class UserPriorityStateSerializer(serializers.ModelSerializer):
    state = StateChoiceField(choices=AustralianState.values, allow_null=True, required=False)

    class Meta:
        model = UserPriorityState
        fields = ['state', 'budget_min', 'budget_max', 'priority_slider_position', 'active_core_mode', 'updated_at']
        read_only_fields = ['updated_at']

    def validate_priority_slider_position(self, value):
        if value is None:
            return value
        if value not in PRIORITY_STOPS:
            raise serializers.ValidationError("invalid_stop")
        return value

    def validate_budget_max(self, value):
        # Whole dollars, multiple of 5,000, in 20,000–200,000; null = state default.
        if value is None:
            return None
        if (value < BUDGET_MIN_DOLLARS or value > BUDGET_MAX_DOLLARS
                or value % BUDGET_STEP_DOLLARS != 0):
            raise serializers.ValidationError("invalid_budget")
        return value

class CurrentVehicleCreateSerializer(serializers.Serializer):
    vehicle_catalogue_id = serializers.UUIDField(required=False, allow_null=True)
    green_vehicle_guide_record_id = serializers.UUIDField(required=False, allow_null=True)
    ai_vehicle_entry_id = serializers.UUIDField(required=False, allow_null=True)
    manual_entry_data = serializers.JSONField(required=False, allow_null=True)
    purchase_date = serializers.DateField(required=False, allow_null=True)
    licence_plate = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    odometer_reading = serializers.IntegerField(required=False, allow_null=True)
    state = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_state(self, value):
        if value in (None, ''):
            return None
        value = str(value).upper()
        if value not in AustralianState.values:
            raise serializers.ValidationError("invalid_state")
        return value

    def validate_vehicle_catalogue_id(self, value):
        if value and not Vehicle.objects.filter(id=value).exists():
            raise serializers.ValidationError("Vehicle with this ID does not exist in the catalogue.")
        return value

    def validate_green_vehicle_guide_record_id(self, value):
        from apps.vehicles.models import VehicleIdentity
        if value and not VehicleIdentity.objects.filter(id=value).exists():
            raise serializers.ValidationError("Green Vehicle Guide record with this ID does not exist.")
        return value

    def validate_ai_vehicle_entry_id(self, value):
        from apps.vehicles.models import AIVehicleEntry
        if value and not AIVehicleEntry.objects.filter(id=value).exists():
            raise serializers.ValidationError("AI vehicle entry with this ID does not exist.")
        return value

    def validate(self, data):
        provided = [k for k in ('vehicle_catalogue_id', 'green_vehicle_guide_record_id',
                                'ai_vehicle_entry_id') if data.get(k)]
        if len(provided) > 1:
            raise serializers.ValidationError(
                "Provide only one of vehicle_catalogue_id, green_vehicle_guide_record_id or ai_vehicle_entry_id."
            )
        return data

class GarageVehicleCreateSerializer(serializers.Serializer):
    vehicle_catalogue_id = serializers.UUIDField()
    source = serializers.ChoiceField(choices=GarageVehicleSource.choices)
    
    def validate_vehicle_catalogue_id(self, value):
        if value and not Vehicle.objects.filter(id=value).exists():
            raise serializers.ValidationError("Vehicle with this ID does not exist in the catalogue.")
        return value
    
class VehicleDetailOverrideSerializer(serializers.Serializer):
    field_name = serializers.CharField()
    override_value = serializers.JSONField()

class AISmartMatchInputSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=500, required=True)
    state = serializers.ChoiceField(
        choices=['NSW', 'VIC', 'QLD', 'SA', 'WA', 'NT', 'TAS', 'ACT'], 
        required=False,
        allow_null=True
    )

import re
from apps.mygarage.models import RideRevealResult

class RideRevealGenerateSerializer(serializers.Serializer):
    garage_vehicle_id = serializers.UUIDField(required=True)
    custom_plate = serializers.CharField(max_length=7, required=False, allow_blank=True, allow_null=True)

    def validate_custom_plate(self, value):
        if value:
            if not re.match(r'^[A-Za-z0-9]+$', value):
                raise serializers.ValidationError("Custom plate must be alphanumeric only (A-Z, 0-9) and up to 7 characters.")
        return value

class RideRevealPurchaseSerializer(serializers.Serializer):
    purchase_type = serializers.ChoiceField(choices=['single', 'bundle'], required=True)

class RideRevealResultSerializer(serializers.ModelSerializer):
    vehicle = serializers.SerializerMethodField()

    class Meta:
        model = RideRevealResult
        fields = [
            'archetype_name', 'archetype_tagline', 'self_insight_text', 
            'social_perception_text', 'did_you_know_fact', 'share_caption',
            'disclaimer', 'custom_plate', 'generated_at', 'vehicle'
        ]

    def get_vehicle(self, obj):
        from apps.vehicles.services.rating_engine import calculate_core_rating
        from apps.mygarage.models import VehicleOverride
        vehicle = obj.vehicle_catalogue
        user = obj.user
        
        cv = getattr(user, 'current_vehicle', None)
        state = cv.state if cv and cv.state else 'NSW'
        
        priority_state = getattr(user, 'priority_state', None)
        priority = priority_state.priority_slider_position if priority_state else 3
        mode = priority_state.active_core_mode if priority_state else 'pure_cost'
        
        overrides_qs = VehicleOverride.objects.filter(user=user, garage_vehicle=obj.garage_vehicle)
        user_inputs = {o.field_name: o.override_value for o in overrides_qs}
        
        engine_data = calculate_core_rating(vehicle, state, priority, mode, user_inputs)
        
        return {
            'make': vehicle.brand,
            'model': vehicle.model,
            'year': vehicle.year,
            'variant': vehicle.variant,
            'powertrain_type': vehicle.powertrain_type,
            'image_url': vehicle.image_url,
            'core_rating': engine_data.get('core_rating'),
            'band_name': engine_data.get('band_name')
        }

def is_valid_australian_postcode(postcode: str) -> bool:
    if not postcode.isdigit() or len(postcode) != 4:
        return False
    val = int(postcode)
    if val < 200 or val > 9999:
        return False
    if 300 <= val <= 799:
        return False
    if (200 <= val <= 299) or (800 <= val <= 899) or (1000 <= val <= 9999):
        return True
    return False

class FindDealerRequestSerializer(serializers.Serializer):
    # Either a garage vehicle (brand derived from it) or an explicit brand.
    garage_vehicle_id = serializers.UUIDField(required=False)
    brand = serializers.CharField(required=False, max_length=255)
    postcode = serializers.CharField(required=True)
    radius_km = serializers.IntegerField(required=True)

    def validate(self, attrs):
        if not attrs.get('garage_vehicle_id') and not attrs.get('brand'):
            raise serializers.ValidationError(
                {'garage_vehicle_id': 'Either garage_vehicle_id or brand is required.'}
            )
        return attrs

    def validate_postcode(self, value):
        if not is_valid_australian_postcode(value):
            raise serializers.ValidationError("invalid_postcode")
        return value

    def validate_radius_km(self, value):
        if value not in [5, 25, 50, 100]:
            raise serializers.ValidationError("invalid_radius")
        return value

    def validate_brand(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("invalid_brand")
        return value

class DealerLinkClickedSerializer(serializers.Serializer):
    vehicle_brand = serializers.CharField(required=True, max_length=255)
    dealer_name = serializers.CharField(required=False, max_length=255, allow_blank=True)
    vehicle_id = serializers.UUIDField(required=False)
    link_url = serializers.URLField(required=False)

