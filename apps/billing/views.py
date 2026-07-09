from rest_framework import views, status, generics
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.conf import settings
from apps.billing.services import process_stripe_webhook_event
from apps.billing.models import PaymentRecord, SubscriptionPlan
from apps.billing.serializers import PaymentRecordSerializer
import stripe
import logging

logger = logging.getLogger(__name__)
stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', None)

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

class PaymentHistoryView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentRecordSerializer
    
    def get_queryset(self):
        return PaymentRecord.objects.filter(
            user=self.request.user,
            status='succeeded'
        ).order_by('-paid_at')

class PaymentMethodsView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            plan = request.user.subscription_plan
            if not plan.stripe_customer_id:
                return Response([])
                
            payment_methods = stripe.PaymentMethod.list(
                customer=plan.stripe_customer_id,
                type="card",
            )
            
            cards = []
            for pm in payment_methods.data:
                cards.append({
                    "id": pm.id,
                    "brand": pm.card.brand,
                    "last4": pm.card.last4,
                    "exp_month": pm.card.exp_month,
                    "exp_year": pm.card.exp_year,
                    "is_default": False # Stripe customer portal manages defaults natively, but can be derived from customer.invoice_settings.default_payment_method if needed
                })
                
            # If we want to mark the default card
            customer = stripe.Customer.retrieve(plan.stripe_customer_id)
            default_pm = customer.invoice_settings.default_payment_method
            for c in cards:
                if c['id'] == default_pm:
                    c['is_default'] = True
                    
            return Response(cards)
            
        except SubscriptionPlan.DoesNotExist:
            return Response([])
        except Exception as e:
            logger.error(f"Error fetching payment methods: {e}")
            return Response({"error": "Failed to fetch payment methods"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class StripeCustomerPortalView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            plan, _ = SubscriptionPlan.objects.get_or_create(user=request.user)
            if not plan.stripe_customer_id:
                customer = stripe.Customer.create(
                    email=request.user.email,
                    name=f"{request.user.first_name} {request.user.last_name}".strip(),
                    metadata={"user_id": request.user.id}
                )
                plan.stripe_customer_id = customer.id
                plan.save()
                
            return_url = request.data.get('return_url', getattr(settings, 'FRONTEND_URL', 'https://carreb.com.au') + '/billing')
            
            session = stripe.billing_portal.Session.create(
                customer=plan.stripe_customer_id,
                return_url=return_url,
            )
            return Response({"portal_url": session.url})
            
        except Exception as e:
            logger.error(f"Error creating customer portal session: {e}")
            return Response({"error": "Failed to create portal session"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CreateCheckoutSessionView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        plan_type = request.data.get('plan_type')
        if not plan_type:
            return Response({"error": "plan_type is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        # Map plan_type to Stripe Price ID from settings
        price_id = None
        if plan_type == 'car_buying_sprint':
            price_id = getattr(settings, 'STRIPE_PRICE_ID_CAR_BUYING_SPRINT', None)
        elif plan_type == 'core_advantage':
            price_id = getattr(settings, 'STRIPE_PRICE_ID_CORE_ADVANTAGE', None)
        elif plan_type == 'full_insight_pro':
            price_id = getattr(settings, 'STRIPE_PRICE_ID_FULL_INSIGHT_PRO', None)
            
        if not price_id:
            return Response({"error": f"Invalid plan_type or price not configured for {plan_type}"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            plan, _ = SubscriptionPlan.objects.get_or_create(user=request.user)
            if not plan.stripe_customer_id:
                customer = stripe.Customer.create(
                    email=request.user.email,
                    name=f"{request.user.first_name} {request.user.last_name}".strip(),
                    metadata={"user_id": request.user.id}
                )
                plan.stripe_customer_id = customer.id
                plan.save()
                
            return_url = request.data.get('return_url', getattr(settings, 'FRONTEND_URL', 'https://carreb.com.au') + '/billing')
            
            session = stripe.checkout.Session.create(
                customer=plan.stripe_customer_id,
                mode="subscription",
                payment_method_types=["card"],
                line_items=[{
                    "price": price_id,
                    "quantity": 1
                }],
                success_url=return_url + "?success=true&session_id={CHECKOUT_SESSION_ID}",
                cancel_url=return_url + "?canceled=true",
                subscription_data={
                    "metadata": {
                        "user_id": request.user.id,
                        "plan_type": plan_type
                    }
                },
                metadata={
                    "user_id": request.user.id,
                    "plan_type": plan_type
                }
            )
            
            return Response({"checkout_url": session.url})
            
        except Exception as e:
            logger.error(f"Error creating checkout session: {e}")
            return Response({"error": "Failed to create checkout session"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
