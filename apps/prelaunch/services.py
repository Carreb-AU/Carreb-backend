from .models import WaitlistEntry
from .tasks import send_launch_notification_emails_task, send_waitlist_admin_notification_task

def submit_waitlist_email(email: str, source: str = None) -> WaitlistEntry:
    # Use get_or_create to silently handle duplicates
    entry, created = WaitlistEntry.objects.get_or_create(
        email=email,
        defaults={'source': source}
    )
    
    if created:
        send_waitlist_admin_notification_task.delay(email)
        
    return entry

def trigger_launch_emails() -> dict:
    # Trigger celery task asynchronously
    task = send_launch_notification_emails_task.delay()
    
    return {
        "message": "Launch notification emails task has been triggered.",
        "task_id": task.id
    }
