"""
Free Match Wizard — Celery tasks.

cleanup_expired_free_match_sessions
  Runs daily (configured in settings.CELERY_BEAT_SCHEDULE).
  Deletes:
    - Sessions where expires_at has passed AND converted_user is null
      (visitor discarded or never completed the wizard).
    - Sessions where expires_at has passed AND converted_user is set
      AND the session was created more than 30 days ago
      (conversion analytics retention window has elapsed).
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="apps.freematch.tasks.cleanup_expired_free_match_sessions")
def cleanup_expired_free_match_sessions():
    """
    Nightly cleanup of expired FreeMatchSession records.

    Retention rules:
    - Unconverted sessions (converted_user=null): delete immediately once expired.
    - Converted sessions (converted_user set): retain for 30 days from creation
      to support conversion analytics, then delete.
    """
    from apps.freematch.models import FreeMatchSession

    now = timezone.now()
    retention_cutoff = now - timedelta(days=30)

    # Rule 1: Expired + no conversion → delete immediately
    unconverted_qs = FreeMatchSession.objects.filter(
        expires_at__lt=now,
        converted_user__isnull=True,
    )
    unconverted_count, _ = unconverted_qs.delete()

    # Rule 2: Converted but past 30-day analytics window → delete
    converted_qs = FreeMatchSession.objects.filter(
        expires_at__lt=now,
        converted_user__isnull=False,
        created_at__lt=retention_cutoff,
    )
    converted_count, _ = converted_qs.delete()

    logger.info(
        "Free match session cleanup: deleted %d unconverted, %d post-retention converted",
        unconverted_count,
        converted_count,
    )
    return {
        "deleted_unconverted": unconverted_count,
        "deleted_converted_post_retention": converted_count,
    }
