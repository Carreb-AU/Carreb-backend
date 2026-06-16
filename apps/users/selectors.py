from django.utils import timezone
from .models import User, EmailVerificationToken, AuthSession, TwoFactorChallenge, PasswordResetToken

def get_user_by_email(email: str) -> User | None:
    return User.objects.filter(email=email).first()

def get_valid_verification_token(token: str) -> EmailVerificationToken | None:
    return EmailVerificationToken.objects.filter(
        token=token,
        used_at__isnull=True,
        expires_at__gt=timezone.now()
    ).first()

def get_active_session(session_token: str) -> AuthSession | None:
    return AuthSession.objects.filter(
        session_token=session_token,
        revoked_at__isnull=True,
        expires_at__gt=timezone.now()
    ).first()

def get_valid_2fa_challenge(challenge_token: str) -> TwoFactorChallenge | None:
    return TwoFactorChallenge.objects.filter(
        challenge_token=challenge_token,
        verified_at__isnull=True,
        expires_at__gt=timezone.now()
    ).first()

def get_valid_password_reset_token(token: str) -> PasswordResetToken | None:
    return PasswordResetToken.objects.filter(
        token=token,
        used_at__isnull=True,
        expires_at__gt=timezone.now()
    ).first()
