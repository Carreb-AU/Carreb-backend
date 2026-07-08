import re
from rest_framework import serializers
from .models import DeletionReason, TwoFactorMethod, User

def validate_password_complexity(value):
    if len(value) < 8:
        raise serializers.ValidationError("Password must be at least 8 characters long.")
    if not re.search(r'\d', value):
        raise serializers.ValidationError("Password must contain at least one number.")
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', value):
        raise serializers.ValidationError("Password must contain at least one special character.")
    return value

class SignupStep1Serializer(serializers.Serializer):
    email = serializers.EmailField()

class SignupStep2Serializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    mobile_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, validators=[validate_password_complexity])
    environment = serializers.ChoiceField(choices=[('dev', 'dev'), ('production', 'production')], default='dev', required=False)

class EmailVerificationSerializer(serializers.Serializer):
    token = serializers.UUIDField()

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

class Verify2FASerializer(serializers.Serializer):
    challenge_token = serializers.UUIDField()
    totp_code = serializers.CharField(max_length=6, min_length=6)

class SocialLoginSerializer(serializers.Serializer):
    provider = serializers.CharField()
    provider_id = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)

class Confirm2FASerializer(serializers.Serializer):
    totp_code = serializers.CharField(max_length=6, min_length=6)

class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    environment = serializers.ChoiceField(choices=[('dev', 'dev'), ('production', 'production')], default='dev', required=False)

class PasswordResetVerifySerializer(serializers.Serializer):
    token = serializers.UUIDField()
    new_password = serializers.CharField(write_only=True, validators=[validate_password_complexity])

class AccountDeletionRequestSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)
    reason = serializers.ChoiceField(choices=DeletionReason.choices)

class UserProfileSerializer(serializers.ModelSerializer):
    is_2fa_enabled = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email', 'mobile_number', 'profile_picture', 'profile_photo_url', 'subscription_tier', 'email_verified', 'is_2fa_enabled']
        read_only_fields = ['id', 'subscription_tier', 'email_verified', 'is_2fa_enabled']

    def get_is_2fa_enabled(self, obj):
        return hasattr(obj, 'two_factor_auth') and obj.two_factor_auth.is_enabled

class UserProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'mobile_number', 'profile_picture']
