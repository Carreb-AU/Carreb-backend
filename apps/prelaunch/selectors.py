from django.utils import timezone
from .models import WaitlistEntry, PrelaunchConfig

def get_prelaunch_status() -> dict:
    config = PrelaunchConfig.get_solo()
    launch_date = config.launch_date
    current_date = timezone.now().date()
    
    is_prelaunch = current_date < launch_date
    
    return {
        "is_prelaunch": is_prelaunch,
        "launch_date": launch_date
    }

def get_pending_waitlist_entries():
    return WaitlistEntry.objects.filter(notified_at__isnull=True)
