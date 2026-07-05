from rest_framework import serializers

from apps.freematch.models import (
    FreeMatchSession,
    FuelTypePreference,
    PrimaryUse,
)


class FreeMatchStartSerializer(serializers.Serializer):
    """
    POST /api/free-match/start/
    No fields required — the wizard session is created empty.
    """
    pass


# ── Step data serializers ─────────────────────────────────────────────────────

class Step1DataSerializer(serializers.Serializer):
    has_current_vehicle = serializers.BooleanField()


class Step2DataSerializer(serializers.Serializer):
    current_vehicle_make = serializers.CharField(max_length=100)
    current_vehicle_model = serializers.CharField(max_length=100)
    current_vehicle_year = serializers.IntegerField(min_value=1900, max_value=2100)


class Step3DataSerializer(serializers.Serializer):
    fuel_type_preference = serializers.ChoiceField(
        choices=FuelTypePreference.choices
    )
    annual_km = serializers.IntegerField(min_value=1)
    primary_use = serializers.ChoiceField(choices=PrimaryUse.choices)


# ── Step wrapper ─────────────────────────────────────────────────────────────

class FreeMatchStepSerializer(serializers.Serializer):
    """
    PATCH /api/free-match/{session_token}/step/

    Validates step_number is an integer and step_data is a dict.
    Per-step field validation is delegated to Step*DataSerializer instances
    inside the view, so that we can return field-level errors with the
    correct context (e.g. "step_data.fuel_type_preference is invalid").
    """
    step_number = serializers.IntegerField(min_value=1, max_value=3)
    step_data = serializers.DictField(child=serializers.JSONField())

    def validate_step_number(self, value):
        if value not in (1, 2, 3):
            raise serializers.ValidationError("step_number must be 1, 2, or 3.")
        return value


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
