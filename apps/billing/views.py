from rest_framework import views, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from apps.billing.services import process_stripe_webhook_event
import logging

logger = logging.getLogger(__name__)

class StripeWebhookView(views.APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
        
        # We always return 200 OK to Stripe regardless of internal success
        # to prevent Stripe from retrying infinitely for handled errors.
        try:
            success = process_stripe_webhook_event(payload, sig_header)
            if not success:
                logger.warning("Stripe webhook processing returned false, but returning 200 to Stripe.")
        except Exception as e:
            logger.exception("Unhandled error in Stripe Webhook View")
            
        return Response(status=status.HTTP_200_OK)
