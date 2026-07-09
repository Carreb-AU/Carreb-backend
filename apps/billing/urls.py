from django.urls import path
from apps.billing.views import StripeWebhookView, PaymentHistoryView, PaymentMethodsView, StripeCustomerPortalView, CreateCheckoutSessionView

urlpatterns = [
    path('webhook/', StripeWebhookView.as_view(), name='stripe-webhook-general'),
    path('payment-history/', PaymentHistoryView.as_view(), name='payment-history'),
    path('payment-methods/', PaymentMethodsView.as_view(), name='payment-methods'),
    path('customer-portal/', StripeCustomerPortalView.as_view(), name='stripe-customer-portal'),
    path('create-checkout/', CreateCheckoutSessionView.as_view(), name='create-checkout'),
]
