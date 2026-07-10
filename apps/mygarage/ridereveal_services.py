import stripe
import logging
from django.conf import settings
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from apps.mygarage.models import (
    GarageVehicle, GarageVehicleStatus, RideRevealCredit,
    RideRevealResult, RideRevealJob, RideRevealJobStatus, RideRevealCreditType
)
from apps.users.models import SubscriptionTier

logger = logging.getLogger(__name__)

stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', None)

def _get_or_create_credits(user):
    credits, created = RideRevealCredit.objects.get_or_create(
        user=user,
        defaults={'plan': user.subscription_tier}
    )
    if credits.plan != user.subscription_tier:
        credits.plan = user.subscription_tier
        if user.subscription_tier == SubscriptionTier.CAR_BUYING_SPRINT:
            credits.credits_included = 1
        elif user.subscription_tier == SubscriptionTier.CORE_ADVANTAGE:
            credits.credits_included = 4
        elif user.subscription_tier == SubscriptionTier.FULL_INSIGHT_PRO:
            credits.credits_included = 0
        else:
            credits.credits_included = 0
        credits.save()
    return credits

def get_ridereveal_credits(user):
    credits = _get_or_create_credits(user)
    
    vehicles_with_results = RideRevealResult.objects.filter(user=user).values_list('garage_vehicle_id', flat=True)
    
    return {
        "plan": credits.plan,
        "credits_included": credits.credits_included,
        "credits_purchased": credits.credits_purchased,
        "credits_used": credits.credits_used,
        "credits_available": credits.credits_available,
        "is_unlimited": credits.plan == SubscriptionTier.FULL_INSIGHT_PRO,
        "period_end": credits.period_end,
        "vehicles_with_results": list(vehicles_with_results)
    }

def trigger_ridereveal_generation(user, garage_vehicle_id, custom_plate=None):
    from apps.mygarage.tasks import generate_ridereveal_content
    
    try:
        garage_vehicle = GarageVehicle.objects.get(id=garage_vehicle_id, user=user)
    except GarageVehicle.DoesNotExist:
        return {"status_code": 404, "error": "not_found", "message": "Garage vehicle not found or not owned."}
    
    if garage_vehicle.status != GarageVehicleStatus.ACTIVE:
        return {"status_code": 422, "error": "invalid_status", "message": "Vehicle is not active."}
    
    from apps.vehicles.models import PowertrainType
    vehicle_cat = garage_vehicle.vehicle_catalogue
    if vehicle_cat.powertrain_type == PowertrainType.FCEV:
        return {
            "status_code": 422, 
            "error": "ridereveal_unavailable", 
            "message": "RideReveal is not available for hydrogen vehicles at this time."
        }
        
    try:
        existing_result = RideRevealResult.objects.get(user=user, garage_vehicle=garage_vehicle)
        from apps.mygarage.serializers import RideRevealResultSerializer
        return {
            "status_code": 200,
            "already_generated": True,
            "result": RideRevealResultSerializer(existing_result).data
        }
    except RideRevealResult.DoesNotExist:
        pass

    credits = _get_or_create_credits(user)
    is_unlimited = credits.plan == SubscriptionTier.FULL_INSIGHT_PRO
    
    credit_type = RideRevealCreditType.PLAN_INCLUDED
    
    with transaction.atomic():
        credits = RideRevealCredit.objects.select_for_update().get(id=credits.id)
        
        if not is_unlimited:
            if credits.credits_available <= 0:
                return {
                    "status_code": 402,
                    "error": "insufficient_credits",
                    "credits_available": 0,
                    "purchase_options": {
                        "single": {"price_display": "A$4.99", "credits": 1},
                        "bundle": {"price_display": "A$19.99", "credits": 5}
                    }
                }
            
            # Simple check for what kind of credit was consumed
            if credits.credits_included - credits.credits_used > 0:
                credit_type = RideRevealCreditType.PLAN_INCLUDED
            else:
                credit_type = RideRevealCreditType.PURCHASED_SINGLE
                
            credits.credits_used += 1
            credits.save()
            
        job = RideRevealJob.objects.create(
            user=user,
            garage_vehicle=garage_vehicle,
            custom_plate=custom_plate,
            status=RideRevealJobStatus.PENDING
        )
        
    generate_ridereveal_content.delay(job.id, credit_type)
    
    return {
        "status_code": 200,
        "job_id": str(job.id),
        "status": "pending",
        "estimated_seconds": 5,
        "credits_remaining": credits.credits_available if not is_unlimited else None
    }

def create_stripe_payment_intent(user, purchase_type):
    if purchase_type == 'single':
        amount = 499
    elif purchase_type == 'bundle':
        amount = 1999
    else:
        raise ValueError("Invalid purchase type")
        
    intent = stripe.PaymentIntent.create(
        amount=amount,
        currency='aud',
        metadata={'user_id': str(user.id), 'purchase_type': purchase_type}
    )
    return intent.client_secret

def process_stripe_webhook(payload, sig_header):
    webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)
    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET is not configured.")
        return False
        
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        return False

    if event['type'] in ['payment_intent.succeeded', 'checkout.session.completed']:
        intent_or_session = event['data']['object']
        if hasattr(intent_or_session, 'to_dict'):
            intent_or_session = intent_or_session.to_dict()
            
        metadata = intent_or_session.get('metadata') or {}
        user_id = metadata.get('user_id')
        purchase_type = metadata.get('purchase_type')
        
        # Fallback to client_reference_id for Payment Links
        client_ref = intent_or_session.get('client_reference_id')
        if client_ref and '__' in client_ref:
            parts = client_ref.split('__', 1)
            if not user_id:
                user_id = parts[0]
            if not purchase_type:
                purchase_type = parts[1]
        
        if user_id and purchase_type:
            if purchase_type not in ['single', 'bundle']:
                from apps.billing.services import process_stripe_webhook_event
                return process_stripe_webhook_event(payload, sig_header)
                
            try:
                with transaction.atomic():
                    credits = RideRevealCredit.objects.select_for_update().get(user_id=user_id)
                    if purchase_type == 'single':
                        credits.credits_purchased += 1
                    elif purchase_type == 'bundle':
                        credits.credits_purchased += 5
                    credits.save()
            except ObjectDoesNotExist:
                logger.error(f"User credits not found for user {user_id}")
            except Exception as e:
                # Catch ValidationError (e.g. invalid UUID format) or any other db error gracefully
                logger.error(f"Error updating RideReveal credits for user {user_id}: {e}")
                
    return True
