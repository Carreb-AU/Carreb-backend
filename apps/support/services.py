from django.db import DatabaseError
from rest_framework.exceptions import APIException
from .models import SupportTicket

class SupportServiceUnavailable(APIException):
    status_code = 503
    default_detail = 'Support submission temporarily unavailable. Please try again.'
    default_code = 'service_unavailable'

def create_support_ticket(ticket_type, data, user=None, user_agent=None):
    subscription_tier = None
    if user and user.is_authenticated:
        subscription_tier = getattr(user, 'subscription_tier', None)
        
    try:
        ticket = SupportTicket(
            ticket_type=ticket_type,
            user=user if user and user.is_authenticated else None,
            user_agent=user_agent,
            subscription_tier=subscription_tier,
            **data
        )
        ticket.save()
        return ticket
    except DatabaseError:
        raise SupportServiceUnavailable()
