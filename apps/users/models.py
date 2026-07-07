import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_('The Email must be set'))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('email_verified', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))
        return self.create_user(email, password, **extra_fields)

class AuthProvider(models.TextChoices):
    EMAIL = 'email', 'Email'
    GOOGLE = 'google', 'Google'
    APPLE = 'apple', 'Apple'

class DeletionReason(models.TextChoices):
    TOO_EXPENSIVE = 'too_expensive', 'Too expensive'
    NOT_USEFUL = 'not_useful', 'Not useful'
    FOUND_ALTERNATIVE = 'found_alternative', 'Found an alternative'
    OTHER = 'other', 'Other'

class TwoFactorMethod(models.TextChoices):
    AUTHENTICATOR_APP = 'authenticator_app', 'Authenticator App'
    EMAIL = 'email', 'Email'

class SubscriptionTier(models.TextChoices):
    FREE = 'free', 'Free'
    CAR_BUYING_SPRINT = 'car_buying_sprint', 'Car Buying Sprint'
    CORE_ADVANTAGE = 'core_advantage', 'CORE Advantage'
    FULL_INSIGHT_PRO = 'full_insight_pro', 'Full Insight Pro'

class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(_('first name'), max_length=150, blank=True)
    last_name = models.CharField(_('last name'), max_length=150, blank=True)
    email = models.EmailField(_('email address'), unique=True)
    mobile_number = models.CharField(max_length=20, blank=True, null=True)
    profile_photo_url = models.URLField(max_length=500, blank=True, null=True)
    
    email_verified = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    permanently_deleted_at = models.DateTimeField(null=True, blank=True)
    deletion_reason = models.CharField(max_length=50, choices=DeletionReason.choices, blank=True, null=True)
    
    auth_provider = models.CharField(max_length=20, choices=AuthProvider.choices, default=AuthProvider.EMAIL)
    auth_provider_id = models.CharField(max_length=255, blank=True, null=True)
    
    subscription_tier = models.CharField(max_length=50, choices=SubscriptionTier.choices, default=SubscriptionTier.FREE)
    analytics_consent = models.BooleanField(default=False)
    match_count_used = models.IntegerField(default=0)
    
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email

    def get_match_limit(self):
        if self.subscription_tier == SubscriptionTier.FREE:
            return 5
        elif self.subscription_tier == SubscriptionTier.CAR_BUYING_SPRINT:
            return 15
        else:
            return None # Unlimited

class EmailVerificationToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_verification_tokens')
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class AuthSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auth_sessions')
    session_token = models.UUIDField(default=uuid.uuid4, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    expires_at = models.DateTimeField()
    last_active_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class TwoFactorAuth(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='two_factor_auth')
    method = models.CharField(max_length=50, choices=TwoFactorMethod.choices)
    totp_secret = models.CharField(max_length=255, blank=True, null=True) # Encrypted at service level
    is_enabled = models.BooleanField(default=False)
    enrolled_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class TwoFactorChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='two_factor_challenges')
    challenge_token = models.UUIDField(default=uuid.uuid4, unique=True)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class PasswordResetToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_tokens')
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class AccountDeletionRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='account_deletion_request')
    reason = models.CharField(max_length=50, choices=DeletionReason.choices)
    password_confirmed = models.BooleanField(default=False)
    scheduled_deletion_at = models.DateTimeField()
    requested_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)
