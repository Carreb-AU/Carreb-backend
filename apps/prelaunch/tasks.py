from celery import shared_task
from django.utils import timezone
from django.core.mail import send_mail
import logging
from .selectors import get_pending_waitlist_entries, get_prelaunch_status
from django.conf import settings

logger = logging.getLogger(__name__)

@shared_task
def send_launch_notification_emails_task():
    # Only process if we are no longer in pre-launch mode (i.e. it's launch day or later)
    if get_prelaunch_status()['is_prelaunch']:
        if settings.DEBUG:
            print("[DEV] Launch day not reached. Skipping email notifications.")
        return {"status": "skipped", "reason": "not_launch_day"}

    entries = get_pending_waitlist_entries()
    total_in_waitlist = entries.count()
    total_notified_successfully = 0
    total_failed = 0

    # In Dev, just print. In prod, send actual emails.
    for entry in entries.iterator():
        try:
            if settings.DEBUG:
                print(f"[DEV] Sending Launch Notification Email to: {entry.email}")
            else:
                # Add real email sending logic here for prod later
                print(f"[PROD] Placeholder for real email send to: {entry.email}")
                
            # Update the notified_at timestamp
            entry.notified_at = timezone.now()
            entry.save(update_fields=['notified_at'])
            total_notified_successfully += 1
            
        except Exception as e:
            # Log failure and move on
            print(f"Failed to send email to {entry.email}: {e}")
            total_failed += 1

    return {
        "status": "completed",
        "total_in_waitlist": total_in_waitlist,
        "total_notified_successfully": total_notified_successfully,
        "total_failed": total_failed
    }

@shared_task
def send_waitlist_admin_notification_task(subscriber_email: str):
    try:
        subject = 'New Prelaunch Subscription'
        message = f'Hello,\n\nA new user has subscribed to the prelaunch waitlist.\n\nSubscriber Email: {subscriber_email}\n\nBest,\nCarreb System'
        
        html_message = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <h2 style="color: #2c3e50;">New Prelaunch Subscription 🎉</h2>
                <p>Hello,</p>
                <p>A new user has just subscribed to the Carreb prelaunch waitlist!</p>
                <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #007bff; margin: 20px 0;">
                    <p style="margin: 0;"><strong>Subscriber Email:</strong> {subscriber_email}</p>
                </div>
                <p>Best regards,<br><strong>Carreb System</strong></p>
            </body>
        </html>
        """
        
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@carreb.com.au')
        admin_email = 'contact@carreb.com.au'
        
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[admin_email],
            fail_silently=False,
            html_message=html_message
        )
        logger.info(f"Admin notification email sent for new subscriber: {subscriber_email}")
    except Exception as e:
        logger.exception(f"Failed to send admin notification email for {subscriber_email}: {e}")
