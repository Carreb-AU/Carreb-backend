from django.contrib import admin
from .models import (
    User,
    EmailVerificationToken,
    AuthSession,
    TwoFactorAuth,
    TwoFactorChallenge,
    PasswordResetToken,
    AccountDeletionRequest
)

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'is_active', 'is_staff', 'created_at')
    search_fields = ('email', 'first_name', 'last_name')
    list_filter = ('is_active', 'is_staff', 'is_deleted', 'auth_provider')
    ordering = ('-created_at',)

@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'token', 'expires_at', 'used_at', 'created_at')
    search_fields = ('user__email',)
    list_filter = ('used_at',)

@admin.register(AuthSession)
class AuthSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'ip_address', 'expires_at', 'last_active_at', 'revoked_at')
    search_fields = ('user__email', 'ip_address')
    list_filter = ('revoked_at',)

@admin.register(TwoFactorAuth)
class TwoFactorAuthAdmin(admin.ModelAdmin):
    list_display = ('user', 'method', 'is_enabled', 'enrolled_at', 'disabled_at')
    search_fields = ('user__email',)
    list_filter = ('method', 'is_enabled')

@admin.register(TwoFactorChallenge)
class TwoFactorChallengeAdmin(admin.ModelAdmin):
    list_display = ('user', 'expires_at', 'verified_at', 'created_at')
    search_fields = ('user__email',)
    list_filter = ('verified_at',)

@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'token', 'expires_at', 'used_at', 'created_at')
    search_fields = ('user__email',)
    list_filter = ('used_at',)

@admin.register(AccountDeletionRequest)
class AccountDeletionRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'reason', 'scheduled_deletion_at', 'requested_at', 'executed_at')
    search_fields = ('user__email',)
    list_filter = ('reason', 'executed_at')
