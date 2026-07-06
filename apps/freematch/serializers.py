from rest_framework import serializers

from apps.freematch.models import (
    FuelTypePreference,
    PrimaryUse,
    PriorityPreference,
)

class CurrentVehicleDataSerializer(serializers.Serializer):
    make = serializers.CharField(max_length=100)
    model = serializers.CharField(max_length=100)
    year = serializers.IntegerField(min_value=1900, max_value=2100)
    odometer = serializers.IntegerField(min_value=0, allow_null=True, required=False)


class SpecificNeedsDataSerializer(serializers.Serializer):
    fuel_type = serializers.ChoiceField(
        choices=FuelTypePreference.choices,
        allow_null=True,
        required=False
    )
    style = serializers.CharField(max_length=100, allow_null=True, required=False)
    seating = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    ancap_5_star_only = serializers.BooleanField(default=False)
    towing_capacity_required = serializers.BooleanField(default=False)


class FreeMatchCalculateSerializer(serializers.Serializer):
    priority = serializers.ChoiceField(choices=PriorityPreference.choices, default=PriorityPreference.BALANCED)
    primary_use = serializers.ChoiceField(choices=PrimaryUse.choices)
    annual_km = serializers.IntegerField(min_value=1)
    budget_min = serializers.IntegerField(min_value=0, allow_null=True, required=False)
    budget_max = serializers.IntegerField(min_value=0, allow_null=True, required=False)
    state = serializers.CharField(max_length=10, allow_null=True, required=False)
    
    has_current_vehicle = serializers.BooleanField(default=False)
    current_vehicle = CurrentVehicleDataSerializer(required=False, allow_null=True)
    
    specific_needs = SpecificNeedsDataSerializer(required=False, allow_null=True)

    def validate(self, data):
        if data.get("has_current_vehicle") and not data.get("current_vehicle"):
            raise serializers.ValidationError({"current_vehicle": "This field is required when has_current_vehicle is true."})
        return data


# ── Gated field shape ─────────────────────────────────────────────────────────

class LockedFieldSerializer(serializers.Serializer):
    locked = serializers.BooleanField(default=True)
    value = serializers.SerializerMethodField()

    def get_value(self, _obj):
        return None


# ── Response serializers ──────────────────────────────────────────────────────

class PartialVehicleResultSerializer(serializers.Serializer):
    """
    Partial (anonymous) match result — gated fields are locked: true, value: null.
    """
    id = serializers.UUIDField()
    make = serializers.CharField()
    model = serializers.CharField()
    year = serializers.IntegerField()
    variant = serializers.CharField()
    powertrain_type = serializers.CharField()

    # Visible to everyone
    core_rating = serializers.FloatField(allow_null=True)
    band_name = serializers.CharField(allow_null=True)
    annual_running_cost_estimate = serializers.IntegerField()
    annual_running_cost_display = serializers.CharField()
    co2_g_per_km = serializers.FloatField(allow_null=True)
    is_estimate = serializers.BooleanField(default=True)

    # Gated
    resale_value_5yr_estimate = serializers.DictField()
    est_cost_difference = serializers.DictField()
    driveaway_price_estimate = serializers.DictField()
