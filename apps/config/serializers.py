from rest_framework import serializers
from .models import SiteConfig


class SiteConfigSerializer(serializers.ModelSerializer):
    """Read-only serializer for the public / config API."""

    class Meta:
        model = SiteConfig
        fields = (
            'site_name',
            'default_meta_title',
            'default_meta_description',
            'canonical_host',
            'ga4_measurement_id',
            'legal_effective_date',
            'homepage_vehicle_count_claim',
            'organization_json_ld',
            'extra_head_tags',
            'updated_at',
        )
        read_only_fields = fields
