from django.contrib import admin
from django.utils.html import format_html

from apps.users.models import (
    User,
    EmailVerificationToken,
    AuthSession,
    TwoFactorAuth,
    TwoFactorChallenge,
    PasswordResetToken,
    AccountDeletionRequest,
    NotificationPreference,
    FCMDevice,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = [
        "email",
        "full_name",
        "subscription_tier",
        "auth_provider",
        "email_verified",
        "is_active",
        "is_deleted",
        "analytics_consent",
        "created_at",
    ]
    search_fields = ["email", "first_name", "last_name"]
    list_filter = [
        "subscription_tier",
        "auth_provider",
        "email_verified",
        "is_active",
        "is_deleted",
        "is_staff",
        "analytics_consent",
    ]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"

    fieldsets = (
        ("Identity", {
            "fields": ("id", "email", "first_name", "last_name", "mobile_number", "profile_photo_url"),
        }),
        ("Authentication", {
            "fields": ("auth_provider", "auth_provider_id", "email_verified"),
        }),
        ("Account Status", {
            "fields": (
                "is_active", "is_staff", "is_superuser",
                "is_deleted", "deleted_at", "permanently_deleted_at", "deletion_reason",
            ),
        }),
        ("Subscription & Consent", {
            "fields": ("subscription_tier", "analytics_consent"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    @admin.display(description="Name")
    def full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip() or "—"


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "token", "expires_at", "used_at", "created_at"]
    search_fields = ["user__email"]
    list_filter = ["used_at"]
    readonly_fields = ["id", "token", "created_at"]
    raw_id_fields = ["user"]
    ordering = ["-created_at"]


@admin.register(AuthSession)
class AuthSessionAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "ip_address",
        "expires_at",
        "last_active_at",
        "revoked_at",
        "created_at",
    ]
    search_fields = ["user__email", "ip_address"]
    list_filter = ["revoked_at"]
    readonly_fields = ["id", "session_token", "created_at"]
    raw_id_fields = ["user"]
    ordering = ["-created_at"]

    fieldsets = (
        ("Session", {
            "fields": ("id", "session_token", "user"),
        }),
        ("Client Info", {
            "fields": ("ip_address", "user_agent"),
        }),
        ("Lifecycle", {
            "fields": ("expires_at", "last_active_at", "revoked_at", "created_at"),
        }),
    )


@admin.register(TwoFactorAuth)
class TwoFactorAuthAdmin(admin.ModelAdmin):
    list_display = ["user", "method", "is_enabled", "enrolled_at", "disabled_at"]
    search_fields = ["user__email"]
    list_filter = ["method", "is_enabled"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["user"]
    ordering = ["-created_at"]


@admin.register(TwoFactorChallenge)
class TwoFactorChallengeAdmin(admin.ModelAdmin):
    list_display = ["user", "challenge_token", "expires_at", "verified_at", "created_at"]
    search_fields = ["user__email"]
    list_filter = ["verified_at"]
    readonly_fields = ["id", "challenge_token", "created_at"]
    raw_id_fields = ["user"]
    ordering = ["-created_at"]


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "token", "expires_at", "used_at", "created_at"]
    search_fields = ["user__email"]
    list_filter = ["used_at"]
    readonly_fields = ["id", "token", "created_at"]
    raw_id_fields = ["user"]
    ordering = ["-created_at"]


@admin.register(AccountDeletionRequest)
class AccountDeletionRequestAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "reason",
        "password_confirmed",
        "scheduled_deletion_at",
        "requested_at",
        "executed_at",
    ]
    search_fields = ["user__email"]
    list_filter = ["reason", "executed_at"]
    readonly_fields = ["id", "requested_at"]
    raw_id_fields = ["user"]
    ordering = ["-requested_at"]

    fieldsets = (
        ("User", {
            "fields": ("id", "user"),
        }),
        ("Request", {
            "fields": ("reason", "password_confirmed", "requested_at"),
        }),
        ("Scheduled Deletion", {
            "fields": ("scheduled_deletion_at", "executed_at"),
        }),
    )

@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "email_marketing_enabled", "app_notifications_enabled", "sms_notifications_enabled"]
    search_fields = ["user__email"]
    raw_id_fields = ["user"]
    readonly_fields = ["created_at", "updated_at"]

@admin.register(FCMDevice)
class FCMDeviceAdmin(admin.ModelAdmin):
    list_display = ["user", "device_type", "device_id", "created_at"]
    search_fields = ["user__email", "device_id", "fcm_token"]
    list_filter = ["device_type"]
    raw_id_fields = ["user"]
    readonly_fields = ["id", "created_at", "updated_at"]
