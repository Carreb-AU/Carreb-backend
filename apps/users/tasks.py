import logging
from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
from .models import AccountDeletionRequest, User

logger = logging.getLogger(__name__)

@shared_task
def send_verification_email_task(email: str, token_str: str):
    try:
        subject = 'Verify Your Email for Carreb'
        verification_link = f'{settings.FRONTEND_URL}/signup/details?token={token_str}'
        context = {'verification_link': verification_link}
        html_message = render_to_string('emails/verification.html', context)
        plain_message = f'Please verify your email by clicking the following link: {verification_link}'
        from_email = settings.DEFAULT_FROM_EMAIL
        send_mail(subject, plain_message, from_email, [email], html_message=html_message, fail_silently=False)
        logger.info(f"Verification email sent to {email}")
    except Exception as e:
        logger.exception(f"Failed to send verification email to {email}: {e}")

@shared_task
def send_deletion_confirmation_email_task(email: str):
    try:
        subject = 'Carreb Account Deletion Initiated'
        message = 'Your account has been scheduled for deletion in 30 days. Log in before then to cancel this request.'
        from_email = settings.DEFAULT_FROM_EMAIL
        send_mail(subject, message, from_email, [email], fail_silently=False)
        logger.info(f"Deletion confirmation email sent to {email}")
    except Exception as e:
        logger.exception(f"Failed to send deletion confirmation email to {email}: {e}")

@shared_task
def send_password_reset_email_task(email: str, token_str: str):
    try:
        subject = 'Reset Your Password for Carreb'
        reset_link = f'{settings.FRONTEND_URL}/reset-password?token={token_str}'
        context = {'reset_link': reset_link}
        html_message = render_to_string('emails/password_reset_link.html', context)
        plain_message = f'Please reset your password by clicking the following link: {reset_link}'
        from_email = settings.DEFAULT_FROM_EMAIL
        send_mail(subject, plain_message, from_email, [email], html_message=html_message, fail_silently=False)
        logger.info(f"Password reset email sent to {email}")
    except Exception as e:
        logger.exception(f"Failed to send password reset email to {email}: {e}")

@shared_task
def purge_deleted_accounts_task():
    now = timezone.now()
    pending_deletions = AccountDeletionRequest.objects.filter(
        scheduled_deletion_at__lte=now,
        executed_at__isnull=True
    ).select_related('user')
    
    for req in pending_deletions:
        user = req.user
        logger.info(f"Permanently purging user: {user.id}")
        user.permanently_deleted_at = now
        user.save(update_fields=['permanently_deleted_at'])
        
        req.executed_at = now
        req.save(update_fields=['executed_at'])
