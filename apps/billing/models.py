import uuid
from django.db import models
from apps.users.models import User

class PlanType(models.TextChoices):
    FREE_STARTER = 'free_starter', 'Free Starter'
    CAR_BUYING_SPRINT = 'car_buying_sprint', 'Car Buying Sprint'
    CORE_ADVANTAGE = 'core_advantage', 'CORE Advantage'
    FULL_INSIGHT_PRO = 'full_insight_pro', 'Full Insight Pro'

class SubscriptionStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    CANCELLED = 'cancelled', 'Cancelled'
    DOWNGRADE_SCHEDULED = 'downgrade_scheduled', 'Downgrade Scheduled'
    CANCELLATION_SCHEDULED = 'cancellation_scheduled', 'Cancellation Scheduled'
    PAST_DUE = 'past_due', 'Past Due'
    SUSPENDED = 'suspended', 'Suspended'

class PurchaseType(models.TextChoices):
    SUBSCRIPTION = 'subscription', 'Subscription'
    RIDEREVEAL_SINGLE = 'ridereveal_single', 'RideReveal Single'
    RIDEREVEAL_BUNDLE = 'ridereveal_bundle', 'RideReveal Bundle'

class PaymentStatus(models.TextChoices):
    SUCCEEDED = 'succeeded', 'Succeeded'
    FAILED = 'failed', 'Failed'
    REFUNDED = 'refunded', 'Refunded'
    PENDING = 'pending', 'Pending'

class SubscriptionPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='subscription_plan')
    plan_type = models.CharField(max_length=50, choices=PlanType.choices, default=PlanType.FREE_STARTER)
    status = models.CharField(max_length=50, choices=SubscriptionStatus.choices, default=SubscriptionStatus.ACTIVE)
    
    stripe_customer_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True)
    
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    
    downgrade_to = models.CharField(max_length=50, choices=PlanType.choices, null=True, blank=True)
    downgrade_at = models.DateTimeField(null=True, blank=True)
    
    pro_acknowledgement_recorded = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.plan_type} ({self.status})"


class PaymentRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_records')
    
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_invoice_id = models.CharField(max_length=255, null=True, blank=True)
    
    amount_cents = models.IntegerField()
    amount_display = models.CharField(max_length=50)
    currency = models.CharField(max_length=10, default='aud')
    
    plan_type = models.CharField(max_length=50, choices=PlanType.choices, null=True, blank=True)
    purchase_type = models.CharField(max_length=50, choices=PurchaseType.choices)
    status = models.CharField(max_length=50, choices=PaymentStatus.choices)
    
    payment_method_last4 = models.CharField(max_length=4, null=True, blank=True)
    payment_method_brand = models.CharField(max_length=50, null=True, blank=True)
    
    invoice_pdf_url = models.URLField(max_length=1024, null=True, blank=True)
    carreb_invoice_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.amount_display} - {self.status}"


class StripeWebhookLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stripe_event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=255)
    payload = models.JSONField()
    processed = models.BooleanField(default=False)
    processing_error = models.TextField(null=True, blank=True)
    
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.event_type} - {self.stripe_event_id} (Processed: {self.processed})"
