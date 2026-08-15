from rest_framework.permissions import BasePermission
from apps.users.models import SubscriptionTier


class IsPaidMember(BasePermission):
    """
    Allow access only to authenticated users with a paid subscription tier.
    Free / starter tiers are rejected.
    """

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.subscription_tier != SubscriptionTier.FREE
        )
