from rest_framework import serializers
from apps.vehicles.models import Vehicle

class VehicleListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = [
            'id', 'brand', 'model', 'year', 'variant', 'body_style',
            'num_seats', 'powertrain_type', 'fcai_category', 'fcai_broad',
            'ancap_safety_rating', 'energy_norm', 'drive', 'engine_l',
            'battery_kwh', 'is_scoring_outlier', 'scoring_version', 'image_url',
            'research_status', 'energy_type', 'cost_category', 'au_launch',
        ]

class VehicleDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = '__all__'

class CoreRatingRequestSerializer(serializers.Serializer):
    vehicle_id = serializers.UUIDField()
    state = serializers.ChoiceField(choices=['NSW', 'VIC', 'QLD', 'SA', 'WA', 'NT', 'TAS', 'ACT'], required=False)
    priority_slider = serializers.IntegerField(min_value=1, max_value=5, default=3)
    core_mode = serializers.ChoiceField(choices=['pure_cost', 'cool_choice', 'true_value', 'full_picture'])
    user_inputs = serializers.DictField(required=False, default=dict)
    current_vehicle_annual_cost = serializers.IntegerField(required=False, allow_null=True)
    budget_min = serializers.IntegerField(required=False, allow_null=True)
    budget_max = serializers.IntegerField(required=False, allow_null=True)

class CoreRatingBatchRequestSerializer(serializers.Serializer):
    vehicle_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=30
    )
    state = serializers.ChoiceField(choices=['NSW', 'VIC', 'QLD', 'SA', 'WA', 'NT', 'TAS', 'ACT'], required=False)
    priority_slider = serializers.IntegerField(min_value=1, max_value=5, default=3)
    core_mode = serializers.ChoiceField(choices=['pure_cost', 'cool_choice', 'true_value', 'full_picture'])
    user_inputs = serializers.DictField(required=False, default=dict)
    current_vehicle_annual_cost = serializers.IntegerField(required=False, allow_null=True)
    budget_min = serializers.IntegerField(required=False, allow_null=True)
    budget_max = serializers.IntegerField(required=False, allow_null=True)

class CoreSearchRequestSerializer(serializers.Serializer):
    target_band_slug = serializers.CharField()
    fcai_category = serializers.CharField(required=False, allow_null=True)
    state = serializers.ChoiceField(choices=['NSW', 'VIC', 'QLD', 'SA', 'WA', 'NT', 'TAS', 'ACT'], required=False)
    priority_slider = serializers.IntegerField(min_value=1, max_value=5, default=3)
    core_mode = serializers.ChoiceField(choices=['pure_cost', 'cool_choice', 'true_value', 'full_picture'])
    user_inputs = serializers.DictField(required=False, default=dict)
    current_vehicle_annual_cost = serializers.IntegerField(required=False, allow_null=True)
    budget_min = serializers.IntegerField(required=False, allow_null=True)
    budget_max = serializers.IntegerField(required=False, allow_null=True)
