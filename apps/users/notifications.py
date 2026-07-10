import logging
from django.conf import settings
from django.core.mail import send_mail
from twilio.rest import Client
import firebase_admin
from firebase_admin import messaging

logger = logging.getLogger(__name__)

def send_notification(user, subject, message, notification_type='product_news'):
    """
    Unified notification sender. Checks user preferences before dispatching.
    """
    if not hasattr(user, 'notification_preferences'):
        return # Skip if no preferences
        
    prefs = user.notification_preferences
    
    # Check Email Preferences
    if prefs.email_marketing_enabled:
        # Check specific notification type
        if getattr(prefs, f"email_{notification_type}", False):
            try:
                send_mail(
                    subject,
                    message,
                    settings.EMAIL_HOST_USER,
                    [user.email],
                    fail_silently=True,
                )
            except Exception as e:
                logger.error(f"Failed to send email to {user.email}: {e}")
                
    # Check App Push Preferences
    if prefs.app_notifications_enabled:
        if getattr(prefs, f"app_{notification_type}", False):
            try:
                devices = user.fcm_devices.all()
                for device in devices:
                    try:
                        msg = messaging.Message(
                            notification=messaging.Notification(title=subject, body=message),
                            token=device.fcm_token,
                        )
                        messaging.send(msg)
                    except Exception as dev_err:
                        logger.error(f"Failed to send push to device {device.device_id}: {dev_err}")
                
                logger.info(f"Sent FCM push to {devices.count()} devices for {user.email}")
            except Exception as e:
                logger.error(f"Failed to send push notification: {e}")

def send_sms_notification(user, message):
    """
    Sends an SMS using Twilio, respecting the SMS opt-in toggle.
    """
    if not hasattr(user, 'notification_preferences'):
        return
        
    prefs = user.notification_preferences
    if not prefs.sms_notifications_enabled:
        return
        
    if not user.mobile_number:
        logger.warning(f"User {user.email} opted into SMS but has no mobile number.")
        return
        
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=user.mobile_number
        )
    except Exception as e:
        logger.error(f"Failed to send Twilio SMS to {user.mobile_number}: {e}")
