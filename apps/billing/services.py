import stripe
import logging
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from datetime import timedelta
from apps.billing.models import (
    SubscriptionPlan, PaymentRecord, StripeWebhookLog,
    PlanType, SubscriptionStatus, PaymentStatus, PurchaseType
)
from apps.users.models import User, SubscriptionTier
from apps.mygarage.models import GarageVehicle, GarageVehicleStatus

logger = logging.getLogger(__name__)
stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', None)

def get_user_entitlements(user):
    try:
        plan = user.subscription_plan
        plan_type = plan.plan_type
        status = plan.status
        
        # If suspended, fallback to free limits for features
        if status == SubscriptionStatus.SUSPENDED:
            plan_type = PlanType.FREE_STARTER
    except ObjectDoesNotExist:
        plan_type = PlanType.FREE_STARTER
        
    entitlements = {
        'plan_type': plan_type,
        'vehicle_limit': 1,
        'match_limit': 5, # From users/models.py
        'match_lifetime_total': False,
        'core_modes_available': ['pure_cost'],
        'spotlights_available': False,
        'ridereveal_credits_available': 0,
        'ridereveal_unlimited': False,
        'full_insight_pro_acknowledgement_required': False
    }
    
    if plan_type == PlanType.CAR_BUYING_SPRINT:
        entitlements.update({
            'vehicle_limit': 3,
            'match_limit': 15,
            'match_lifetime_total': True,
            'ridereveal_credits_available': 1
        })
    elif plan_type == PlanType.CORE_ADVANTAGE:
        entitlements.update({
            'vehicle_limit': 10,
            'match_limit': None,
            'core_modes_available': ['pure_cost', 'cool_choice', 'true_value', 'full_picture'],
            'spotlights_available': True,
            'ridereveal_credits_available': 4
        })
    elif plan_type == PlanType.FULL_INSIGHT_PRO:
        entitlements.update({
            'vehicle_limit': 30,
            'match_limit': None,
            'core_modes_available': ['pure_cost', 'cool_choice', 'true_value', 'full_picture'],
            'spotlights_available': True,
            'ridereveal_credits_available': None,
            'ridereveal_unlimited': True,
            'full_insight_pro_acknowledgement_required': True
        })
        
    return entitlements

def _sync_user_subscription_tier(user, plan_type):
    # Sync the legacy field
    if plan_type == PlanType.FREE_STARTER:
        user.subscription_tier = SubscriptionTier.FREE
    elif plan_type == PlanType.CAR_BUYING_SPRINT:
        user.subscription_tier = SubscriptionTier.CAR_BUYING_SPRINT
    elif plan_type == PlanType.CORE_ADVANTAGE:
        user.subscription_tier = SubscriptionTier.CORE_ADVANTAGE
    elif plan_type == PlanType.FULL_INSIGHT_PRO:
        user.subscription_tier = SubscriptionTier.FULL_INSIGHT_PRO
    user.save()

def _enforce_vehicle_limits(user):
    entitlements = get_user_entitlements(user)
    limit = entitlements['vehicle_limit']
    
    vehicles = GarageVehicle.objects.filter(
        user=user,
        status__in=[GarageVehicleStatus.ACTIVE, GarageVehicleStatus.ARCHIVED]
    ).order_by('added_at')
    
    count = 0
    for v in vehicles:
        count += 1
        if count > limit:
            v.read_only = True
            v.re_subscribe_required = True
            v.save()
        else:
            if v.read_only and v.re_subscribe_required:
                v.read_only = False
                v.re_subscribe_required = False
                v.save()

def process_stripe_webhook_event(payload, sig_header):
    webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET_BILLING', None)
    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET_BILLING is not configured.")
        return False
        
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        return False

    stripe_event_id = event.get('id')
    event_type = event.get('type')
    
    # Idempotency check
    log_entry, created = StripeWebhookLog.objects.get_or_create(
        stripe_event_id=stripe_event_id,
        defaults={'event_type': event_type, 'payload': event}
    )
    if not created and log_entry.processed:
        return True # Already processed successfully
        
    try:
        with transaction.atomic():
            if event_type == 'payment_intent.succeeded':
                _handle_payment_intent_succeeded(event.get('data', {}).get('object', {}))
            elif event_type == 'invoice.payment_succeeded':
                _handle_invoice_payment_succeeded(event.get('data', {}).get('object', {}))
            elif event_type == 'invoice.payment_failed':
                _handle_invoice_payment_failed(event.get('data', {}).get('object', {}))
            elif event_type == 'customer.subscription.updated':
                _handle_subscription_updated(event.get('data', {}).get('object', {}))
            elif event_type == 'customer.subscription.deleted':
                _handle_subscription_deleted(event.get('data', {}).get('object', {}))
            elif event_type in ['payment_method.attached', 'payment_method.detached']:
                pass # Informational only
                
            log_entry.processed = True
            log_entry.processed_at = timezone.now()
            log_entry.save()
            return True
            
    except Exception as e:
        logger.exception(f"Error processing stripe webhook {stripe_event_id}")
        log_entry.processing_error = str(e)
        log_entry.save()
        return False

def _handle_payment_intent_succeeded(intent):
    metadata = intent.get('metadata', {})
    user_id = metadata.get('user_id')
    plan_type_meta = metadata.get('plan_type')
    purchase_type = metadata.get('purchase_type')
    
    if purchase_type in ['single', 'bundle']:
        # RideReveal purchase. Just log and return.
        return
        
    if plan_type_meta == PlanType.CAR_BUYING_SPRINT and user_id:
        user = User.objects.get(id=user_id)
        plan, _ = SubscriptionPlan.objects.get_or_create(user=user)
        plan.plan_type = PlanType.CAR_BUYING_SPRINT
        plan.status = SubscriptionStatus.ACTIVE
        plan.stripe_payment_intent_id = intent.get('id')
        plan.save()
        
        _sync_user_subscription_tier(user, PlanType.CAR_BUYING_SPRINT)
        
        PaymentRecord.objects.create(
            user=user,
            stripe_payment_intent_id=intent.get('id'),
            amount_cents=intent.get('amount'),
            amount_display=f"A${intent.get('amount') / 100:.2f}",
            currency='aud',
            plan_type=PlanType.CAR_BUYING_SPRINT,
            purchase_type=PurchaseType.SUBSCRIPTION,
            status=PaymentStatus.SUCCEEDED,
            paid_at=timezone.now()
        )
        
        _enforce_vehicle_limits(user)
        # TODO: Queue email (plan activation confirmation)

def _handle_invoice_payment_succeeded(invoice):
    sub_id = invoice.get('subscription')
    customer_id = invoice.get('customer')
    if not sub_id:
        return
        
    try:
        stripe_sub = stripe.Subscription.retrieve(sub_id)
        metadata = stripe_sub.get('metadata', {})
        user_id = metadata.get('user_id')
        plan_type = metadata.get('plan_type')
        
        if not user_id or not plan_type:
            # Fallback to checking existing plan
            try:
                plan = SubscriptionPlan.objects.get(stripe_subscription_id=sub_id)
                user = plan.user
                plan_type = plan.plan_type
            except SubscriptionPlan.DoesNotExist:
                return
        else:
            user = User.objects.get(id=user_id)
            
        plan, created = SubscriptionPlan.objects.get_or_create(user=user)
        plan.stripe_customer_id = customer_id
        plan.stripe_subscription_id = sub_id
        plan.plan_type = plan_type
        plan.status = SubscriptionStatus.ACTIVE
        plan.current_period_start = timezone.datetime.fromtimestamp(stripe_sub.get('current_period_start'), tz=timezone.utc)
        plan.current_period_end = timezone.datetime.fromtimestamp(stripe_sub.get('current_period_end'), tz=timezone.utc)
        
        if plan.cancel_at_period_end:
            plan.cancel_at_period_end = False
            
        plan.save()
        _sync_user_subscription_tier(user, plan_type)
        
        # RideReveal reset handled by period start/end and entitlements
        
        PaymentRecord.objects.create(
            user=user,
            stripe_invoice_id=invoice.get('id'),
            stripe_payment_intent_id=invoice.get('payment_intent'),
            amount_cents=invoice.get('amount_paid'),
            amount_display=f"A${invoice.get('amount_paid') / 100:.2f}",
            currency='aud',
            plan_type=plan_type,
            purchase_type=PurchaseType.SUBSCRIPTION,
            status=PaymentStatus.SUCCEEDED,
            invoice_pdf_url=invoice.get('hosted_invoice_url'),
            paid_at=timezone.now()
        )
        
        _enforce_vehicle_limits(user)
        # TODO: Queue email (signup or renewal)
    except Exception as e:
        logger.error(f"Failed handling invoice {invoice.get('id')}: {e}")

def _handle_invoice_payment_failed(invoice):
    sub_id = invoice.get('subscription')
    if not sub_id:
        return
        
    try:
        plan = SubscriptionPlan.objects.get(stripe_subscription_id=sub_id)
        next_attempt = invoice.get('next_payment_attempt')
        
        if next_attempt:
            plan.status = SubscriptionStatus.PAST_DUE
        else:
            plan.status = SubscriptionStatus.SUSPENDED
            
        plan.save()
        
        if plan.status == SubscriptionStatus.SUSPENDED:
            _enforce_vehicle_limits(plan.user)
            # Revert UI flags etc as needed
    except SubscriptionPlan.DoesNotExist:
        pass

def _handle_subscription_updated(subscription):
    sub_id = subscription.get('id')
    try:
        plan = SubscriptionPlan.objects.get(stripe_subscription_id=sub_id)
        cancel_at_period_end = subscription.get('cancel_at_period_end', False)
        
        if cancel_at_period_end and not plan.cancel_at_period_end:
            plan.status = SubscriptionStatus.CANCELLATION_SCHEDULED
            plan.cancel_at_period_end = True
        elif not cancel_at_period_end and plan.cancel_at_period_end:
            plan.status = SubscriptionStatus.ACTIVE
            plan.cancel_at_period_end = False
            
        # Downgrade logic (plan change scheduling)
        # Usually Stripe handles this via `schedule` or `subscription.items`.
        # Simplification: If metadata has downgrade_to
        metadata = subscription.get('metadata', {})
        if 'downgrade_to' in metadata:
            plan.downgrade_to = metadata.get('downgrade_to')
            plan.downgrade_at = plan.current_period_end
            plan.status = SubscriptionStatus.DOWNGRADE_SCHEDULED
            
        plan.save()
    except SubscriptionPlan.DoesNotExist:
        pass

def _handle_subscription_deleted(subscription):
    sub_id = subscription.get('id')
    try:
        plan = SubscriptionPlan.objects.get(stripe_subscription_id=sub_id)
        
        if plan.downgrade_to:
            new_plan = plan.downgrade_to
        else:
            new_plan = PlanType.FREE_STARTER
            
        plan.plan_type = new_plan
        plan.status = SubscriptionStatus.ACTIVE
        plan.stripe_subscription_id = None
        plan.current_period_start = None
        plan.current_period_end = None
        plan.cancel_at_period_end = False
        plan.downgrade_to = None
        plan.save()
        
        _sync_user_subscription_tier(plan.user, new_plan)
        _enforce_vehicle_limits(plan.user)
        
        # Spotlights / Core modes reverting handled by get_user_entitlements dynamically
    except SubscriptionPlan.DoesNotExist:
        pass
