import pyotp
import logging
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.contrib.auth.hashers import make_password
from rest_framework_simplejwt.tokens import RefreshToken
from .models import (
    User, EmailVerificationToken, AuthSession, TwoFactorAuth, TwoFactorChallenge, 
    PasswordResetToken, AccountDeletionRequest, AuthProvider
)
from .selectors import get_user_by_email, get_valid_verification_token, get_valid_2fa_challenge, get_valid_password_reset_token
from .tasks import send_verification_email_task, send_deletion_confirmation_email_task, send_password_reset_email_task


logger = logging.getLogger(__name__)
SESSION_EXPIRY_DAYS = 30
CHALLENGE_EXPIRY_MINUTES = 10
VERIFICATION_EXPIRY_HOURS = 24

def _create_auth_session(user, ip_address, user_agent):
    expires_at = timezone.now() + timedelta(days=SESSION_EXPIRY_DAYS)
    return AuthSession.objects.create(
        user=user,
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=expires_at
    )

def _get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

def _handle_account_deletion_cancellation(user):
    if user.is_deleted:
        user.is_deleted = False
        user.deleted_at = None
        user.save(update_fields=['is_deleted', 'deleted_at'])
        
        try:
            req = user.account_deletion_request
            req.delete()
        except AccountDeletionRequest.DoesNotExist:
            pass

@transaction.atomic
def signup_step_1(email: str) -> User:
    user = get_user_by_email(email)
    if user and user.email_verified:
        raise ValidationError({"email": "User with this email already exists."})
    
    if not user:
        user = User.objects.create(email=email, email_verified=False)
    return user

@transaction.atomic
def signup_step_2(email: str, first_name: str, last_name: str, password: str, mobile_number: str = None, environment: str = 'dev') -> None:
    user = get_user_by_email(email)
    if not user:
        raise ValidationError({"email": "User does not exist. Please complete step 1."})
    if user.email_verified:
        raise ValidationError({"email": "User is already verified."})
        
    user.first_name = first_name
    user.last_name = last_name
    user.set_password(password)
    if mobile_number:
        user.mobile_number = mobile_number
    user.save()
    
    expires_at = timezone.now() + timedelta(hours=VERIFICATION_EXPIRY_HOURS)
    token_obj = EmailVerificationToken.objects.create(user=user, expires_at=expires_at)
    
    send_verification_email_task.delay(user.email, str(token_obj.token), environment)

@transaction.atomic
def verify_email(token: str) -> AuthSession:
    token_obj = get_valid_verification_token(token)
    if not token_obj:
        raise ValidationError({"token": "Invalid or expired token."})
        
    token_obj.used_at = timezone.now()
    token_obj.save(update_fields=['used_at'])
    
    user = token_obj.user
    
    if token_obj.new_email:
        user.email = token_obj.new_email
        
    user.email_verified = True
    user.save(update_fields=['email', 'email_verified'])
    
    session = _create_auth_session(user, None, None)
    tokens = _get_tokens_for_user(user)
    return {
        "session_token": session.session_token,
        "access": tokens["access"],
        "refresh": tokens["refresh"]
    }

@transaction.atomic
def login(email: str, password: str, ip_address: str, user_agent: str):
    user = get_user_by_email(email)
    if not user:
        raise ValidationError({"detail": "Invalid credentials."})
    
    if user.permanently_deleted_at:
        raise ValidationError({"detail": "Account permanently deleted."})
        
    if not user.check_password(password):
        raise ValidationError({"detail": "Invalid credentials."})
        
    if not user.email_verified:
        raise PermissionDenied({"detail": "Please verify your email first."})
        
    _handle_account_deletion_cancellation(user)
        
    if hasattr(user, 'two_factor_auth') and user.two_factor_auth.is_enabled:
        expires_at = timezone.now() + timedelta(minutes=CHALLENGE_EXPIRY_MINUTES)
        challenge = TwoFactorChallenge.objects.create(user=user, expires_at=expires_at)
        return {
            "type": "challenge", 
            "challenge_token": challenge.challenge_token,
            "is_2fa_enabled": True
        }
        
    session = _create_auth_session(user, ip_address, user_agent)
    tokens = _get_tokens_for_user(user)
    return {
        "type": "session", 
        "session_token": session.session_token,
        "access": tokens["access"],
        "refresh": tokens["refresh"],
        "is_2fa_enabled": False
    }

@transaction.atomic
def verify_login_2fa(challenge_token: str, totp_code: str, ip_address: str, user_agent: str):
    challenge = get_valid_2fa_challenge(challenge_token)
    if not challenge:
        raise ValidationError({"challenge_token": "Invalid or expired challenge."})
        
    user = challenge.user
    tfa = user.two_factor_auth
    
    totp = pyotp.TOTP(tfa.totp_secret)
    if not totp.verify(totp_code):
        raise ValidationError({"totp_code": "Invalid TOTP code."})
        
    challenge.verified_at = timezone.now()
    challenge.save(update_fields=['verified_at'])
    
    session = _create_auth_session(user, ip_address, user_agent)
    tokens = _get_tokens_for_user(user)
    return {
        "session_token": session.session_token,
        "access": tokens["access"],
        "refresh": tokens["refresh"]
    }

@transaction.atomic
def social_login(provider: str, provider_id: str, email: str, first_name: str, last_name: str, ip_address: str, user_agent: str):
    user = get_user_by_email(email)
    if user:
        _handle_account_deletion_cancellation(user)
        if not user.email_verified:
            user.email_verified = True
            user.save(update_fields=['email_verified'])
    else:
        user = User.objects.create(
            email=email,
            first_name=first_name,
            last_name=last_name,
            email_verified=True,
            auth_provider=provider,
            auth_provider_id=provider_id
        )
        
    session = _create_auth_session(user, ip_address, user_agent)
    tokens = _get_tokens_for_user(user)
    return {
        "session_token": session.session_token,
        "access": tokens["access"],
        "refresh": tokens["refresh"]
    }

@transaction.atomic
def setup_2fa(user):
    if hasattr(user, 'two_factor_auth') and user.two_factor_auth.is_enabled:
        raise ValidationError({"detail": "2FA is already enabled."})
        
    tfa, created = TwoFactorAuth.objects.get_or_create(user=user)
    if created or not tfa.totp_secret:
        tfa.totp_secret = pyotp.random_base32()
        tfa.save(update_fields=['totp_secret'])
        
    totp = pyotp.TOTP(tfa.totp_secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name="Carreb")
    return {"provisioning_uri": provisioning_uri, "secret": tfa.totp_secret}

@transaction.atomic
def confirm_2fa(user, totp_code: str):
    if not hasattr(user, 'two_factor_auth') or not user.two_factor_auth.totp_secret:
        raise ValidationError({"detail": "2FA setup has not been initiated."})
        
    tfa = user.two_factor_auth
    if tfa.is_enabled:
        raise ValidationError({"detail": "2FA is already enabled."})
        
    totp = pyotp.TOTP(tfa.totp_secret)
    if not totp.verify(totp_code):
        raise ValidationError({"totp_code": "Invalid TOTP code."})
        
    tfa.is_enabled = True
    tfa.enrolled_at = timezone.now()
    tfa.save(update_fields=['is_enabled', 'enrolled_at'])
    return {"detail": "2FA enabled successfully."}

@transaction.atomic
def delete_account(user: User, password: str, reason: str):
    if not user.check_password(password):
        raise ValidationError({"password": "Invalid password."})
        
    now = timezone.now()
    scheduled_deletion_at = now + timedelta(days=30)
    
    AccountDeletionRequest.objects.create(
        user=user,
        reason=reason,
        password_confirmed=True,
        scheduled_deletion_at=scheduled_deletion_at
    )
    
    user.is_deleted = True
    user.deleted_at = now
    user.save(update_fields=['is_deleted', 'deleted_at'])
    
    AuthSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=now)
    
    send_deletion_confirmation_email_task.delay(user.email)

@transaction.atomic
def password_reset_request(email: str, environment: str = 'dev'):
    user = get_user_by_email(email)
    if not user:
        logger.warning(f"Password reset requested for non-existent email: {email}")
        return
        
    expires_at = timezone.now() + timedelta(hours=1)
    token_obj = PasswordResetToken.objects.create(user=user, expires_at=expires_at)
    
    send_password_reset_email_task.delay(user.email, str(token_obj.token), environment)

@transaction.atomic
def password_reset_verify(token: str, new_password: str):
    token_obj = get_valid_password_reset_token(token)
    if not token_obj:
        raise ValidationError({"token": "Invalid or expired token."})
        
    user = token_obj.user
    user.set_password(new_password)
    user.save(update_fields=['password'])
    
    token_obj.used_at = timezone.now()
    token_obj.save(update_fields=['used_at'])
    
    AuthSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
    logger.info(f"Password reset successfully for {user.email}")

@transaction.atomic
def update_user_profile(user, validated_data, environment='dev'):
    new_email = validated_data.get('email')
    
    # Update fields except email
    if 'first_name' in validated_data:
        user.first_name = validated_data['first_name']
    if 'last_name' in validated_data:
        user.last_name = validated_data['last_name']
    if 'mobile_number' in validated_data:
        user.mobile_number = validated_data['mobile_number']
    if 'profile_picture' in validated_data:
        user.profile_picture = validated_data['profile_picture']
        
    user.save()
    
    email_changed = False
    if new_email and new_email != user.email:
        # Check if new email is already taken
        if User.objects.filter(email=new_email).exclude(id=user.id).exists():
            raise ValidationError({"email": "This email is already in use by another account."})
            
        email_changed = True
        expires_at = timezone.now() + timedelta(hours=VERIFICATION_EXPIRY_HOURS)
        token_obj = EmailVerificationToken.objects.create(
            user=user, 
            new_email=new_email, 
            expires_at=expires_at
        )
        send_verification_email_task.delay(new_email, str(token_obj.token), environment)
        
    return user, email_changed
