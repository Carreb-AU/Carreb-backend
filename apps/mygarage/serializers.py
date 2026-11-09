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
        fields = ['id', 'vehicle_catalogue_id', 'green_vehicle_guide_record_id', 'ai_vehicle_entry_id', 'status', 'source', 'added_at', 'archived_at']

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
        fields = ['state', 'budget_min', 'budget_max', 'priority_slider_position',
                  'active_core_mode', 'garage_km', 'garage_km_user_set', 'updated_at']
        read_only_fields = ['updated_at', 'garage_km_user_set']

    def validate_garage_km(self, value):
        # B-21: whole km/yr within the same guard rails as the odometer
        # derivation; null reverts to automatic (odometer/default).
        if value is None:
            return None
        from apps.vehicles.services.core_dial import GARAGE_KM_MIN, GARAGE_KM_MAX
        if value < GARAGE_KM_MIN or value > GARAGE_KM_MAX:
            raise serializers.ValidationError("invalid_garage_km")
        return value

    def update(self, instance, validated_data):
        # Any explicit garage_km write (value or null) is a user edit: a real
        # value locks it against odometer re-derivation; null unlocks it.
        if 'garage_km' in validated_data:
            instance.garage_km_user_set = validated_data['garage_km'] is not None
        return super().update(instance, validated_data)

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
    garage_km = serializers.IntegerField(required=False, allow_null=True)

    def validate_garage_km(self, value):
        # B-21: same guard rails as the priority-state endpoint.
        if value is None:
            return None
        from apps.vehicles.services.core_dial import GARAGE_KM_MIN, GARAGE_KM_MAX
        if value < GARAGE_KM_MIN or value > GARAGE_KM_MAX:
            raise serializers.ValidationError("invalid_garage_km")
        return value

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
    vehicle_catalogue_id = serializers.UUIDField(required=False, allow_null=True)
    green_vehicle_guide_record_id = serializers.UUIDField(required=False, allow_null=True)
    ai_vehicle_entry_id = serializers.UUIDField(required=False, allow_null=True)
    source = serializers.ChoiceField(choices=GarageVehicleSource.choices)

    def validate_vehicle_catalogue_id(self, value):
        # Existence is enforced in validate(): an id that actually belongs to
        # a GVG or AI record is auto-routed to the right field instead of
        # erroring, so clients that always send the result id here still work.
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
        # Tolerate the search-result id landing in vehicle_catalogue_id:
        # if it really belongs to a GVG or AI record, move it over.
        cid = data.get('vehicle_catalogue_id')
        if cid and not Vehicle.objects.filter(id=cid).exists():
            from apps.vehicles.models import VehicleIdentity, AIVehicleEntry
            if VehicleIdentity.objects.filter(id=cid).exists():
                data['green_vehicle_guide_record_id'] = cid
                data['vehicle_catalogue_id'] = None
            elif AIVehicleEntry.objects.filter(id=cid).exists():
                data['ai_vehicle_entry_id'] = cid
                data['vehicle_catalogue_id'] = None
            else:
                raise serializers.ValidationError({
                    'vehicle_catalogue_id': "Vehicle with this ID does not exist in the catalogue."
                })

        provided = [k for k in ('vehicle_catalogue_id', 'green_vehicle_guide_record_id',
                                'ai_vehicle_entry_id') if data.get(k)]
        if len(provided) != 1:
            raise serializers.ValidationError(
                "Provide exactly one of vehicle_catalogue_id, "
                "green_vehicle_guide_record_id or ai_vehicle_entry_id."
            )
        return data
    
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
    favorite_color = serializers.CharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    first_name = serializers.CharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    # Absolute URL of a photo previously uploaded via POST
    # /ridereveal/photo/ (same origin only). Persisted on the result so a
    # reopen shows it even when the user has no profile picture.
    photo_url = serializers.CharField(max_length=500, required=False,
                                      allow_blank=True, allow_null=True)

    def validate_custom_plate(self, value):
        if value:
            if not re.match(r'^[A-Za-z0-9]+$', value):
                raise serializers.ValidationError("Custom plate must be alphanumeric only (A-Z, 0-9) and up to 7 characters.")
        return value

class RideRevealPurchaseSerializer(serializers.Serializer):
    purchase_type = serializers.ChoiceField(choices=['single', 'bundle'], required=True)

class RideRevealResultSerializer(serializers.ModelSerializer):
    vehicle = serializers.SerializerMethodField()
    share_image_url = serializers.SerializerMethodField()
    public_url = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = RideRevealResult
        fields = [
            'archetype_name', 'archetype_tagline', 'self_insight_text',
            'social_perception_text', 'did_you_know_fact', 'share_caption',
            'disclaimer', 'custom_plate', 'favorite_color', 'first_name',
            'traits', 'generated_at', 'vehicle',
            'share_image_url', 'public_url', 'photo_url'
        ]

    def get_photo_url(self, obj):
        # The photo uploaded in the creation modal, persisted on the result
        # (absolute URL for display). Null when the modal photo was never
        # uploaded — the FE then falls back to the user's profile picture.
        if not obj.uploaded_photo:
            return None
        from django.conf import settings
        base = getattr(settings, 'API_BASE_URL', '').rstrip('/')
        path = obj.uploaded_photo.name
        return f"{base}/media/{path}" if not path.startswith(('http://', 'https://', '/')) else path

    def get_public_url(self, obj):
        # B-36: the public landing page (og tags) is the share/copy URL.
        from django.urls import reverse
        from django.conf import settings
        path = reverse('ridereveal-public', kwargs={'result_id': obj.id})
        return getattr(settings, 'API_BASE_URL', '').rstrip('/') + path

    def get_share_image_url(self, obj):
        if not obj.share_image:
            return None
        url = obj.share_image.url
        if url.startswith('/'):
            from django.conf import settings
            return getattr(settings, 'API_BASE_URL', '').rstrip('/') + url
        return url

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

