from celery import shared_task
import logging

logger = logging.getLogger(__name__)

@shared_task
def emit_analytics_event(user_id: str, event_name: str, event_data: dict):
    """
    Emits an analytics event if the user has consented.
    In a real-world scenario, this might push to Segment, Mixpanel, etc.
    """
    logger.info(f"Analytics Event [{event_name}] for user {user_id}: {event_data}")
    # Integration with external provider would go here.
