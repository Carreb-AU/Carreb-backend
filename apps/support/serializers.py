import re
from rest_framework import serializers
from .constants import ALLOWED_TOPICS

class BaseSupportSerializer(serializers.Serializer):
    def validate_topic(self, value):
        if value not in ALLOWED_TOPICS:
            raise serializers.ValidationError(f"Invalid topic. Must be one of: {', '.join(ALLOWED_TOPICS)}")
        return value

    def validate_what_describes_you(self, value):
        if value not in ALLOWED_TOPICS:
            raise serializers.ValidationError(f"Invalid option. Must be one of: {', '.join(ALLOWED_TOPICS)}")
        return value

    def validate_phone_number(self, value):
        if not value:
            return value
        # Must be valid Australian phone format (10 digits, optional +61 prefix)
        # Examples: 0412345678, +61412345678, 61412345678
        # Let's clean the number
        cleaned = re.sub(r'[\s\-()]', '', value)
        
        # Valid patterns
        # 1. 04xxxxxxxx (10 digits)
        # 2. +614xxxxxxxx (12 chars)
        # 3. 614xxxxxxxx (11 digits)
        if re.match(r'^0[2-478]\d{8}$', cleaned) or re.match(r'^\+?61[2-478]\d{8}$', cleaned):
            return cleaned
        raise serializers.ValidationError("Must be a valid Australian phone number.")

class ContactUsSerializer(BaseSupportSerializer):
    first_name = serializers.CharField(required=True)
    last_name = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    topic = serializers.CharField(required=True)
    what_describes_you = serializers.CharField(required=True)
    message = serializers.CharField(required=True, min_length=1, max_length=2000)

class GetInTouchSerializer(ContactUsSerializer):
    # Same fields as ContactUs
    pass

class BugReportSerializer(serializers.Serializer):
    SEVERITY_CHOICES = (
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    )
    message = serializers.CharField(required=True, max_length=2000)
    page_url = serializers.CharField(required=False, allow_blank=True)
    severity = serializers.ChoiceField(choices=[c[0] for c in SEVERITY_CHOICES], required=True)

class FeatureSuggestionSerializer(serializers.Serializer):
    message = serializers.CharField(required=True, max_length=2000)
    feature_area = serializers.CharField(required=False, allow_blank=True)
