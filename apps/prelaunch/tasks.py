from celery import shared_task
from django.utils import timezone
from .selectors import get_pending_waitlist_entries, get_prelaunch_status
from django.conf import settings

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
