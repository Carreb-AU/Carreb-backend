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

_PLAN_INCLUDED_CREDITS = {
    SubscriptionTier.CAR_BUYING_SPRINT: 1,
    SubscriptionTier.CORE_ADVANTAGE: 4,
    SubscriptionTier.FULL_INSIGHT_PRO: 0,
    SubscriptionTier.FREE: 0,
}


def _get_or_create_credits(user):
    credits, created = RideRevealCredit.objects.get_or_create(
        user=user,
        defaults={'plan': user.subscription_tier}
    )
    if created:
        credits.credits_included = _PLAN_INCLUDED_CREDITS.get(
            user.subscription_tier, 0)
        credits.save(update_fields=['credits_included'])
    elif credits.plan != user.subscription_tier:
        credits.plan = user.subscription_tier
        credits.credits_included = _PLAN_INCLUDED_CREDITS.get(
            user.subscription_tier, 0)
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
        "vehicles_with_results": list(vehicles_with_results),
        # One-off sign-up entitlement for free-tier users.
        "free_reveal_available": (
            credits.plan == SubscriptionTier.FREE and not credits.free_reveal_used
        ),
        "free_reveal_used": credits.free_reveal_used,
    }

def normalize_photo_url(photo_url):
    """Reduce an uploaded-photo URL to its MEDIA-relative path.

    Accepts only this origin ('https://api.carreb.com.au/media/x.jpg',
    '/media/x.jpg') so the card renderer can never be pointed at an
    arbitrary remote URL. Returns the relative path, or None when blank.
    Raises ValueError for anything else.
    """
    if not photo_url:
        return None
    from django.conf import settings
    url = str(photo_url).strip()
    base = getattr(settings, 'API_BASE_URL', '').rstrip('/')
    if base and url.startswith(base + '/'):
        url = url[len(base):]
    if url.startswith('/media/'):
        url = url[len('/media/'):]
    if url.startswith(('http://', 'https://', '/')) or '..' in url:
        raise ValueError("photo_url must be a file uploaded to this site's media storage.")
    return url


def trigger_ridereveal_generation(user, garage_vehicle_id, custom_plate=None, favorite_color=None, first_name=None, photo_url=None):
    from apps.mygarage.tasks import generate_ridereveal_content
    
    try:
        garage_vehicle = GarageVehicle.objects.get(id=garage_vehicle_id, user=user)
    except GarageVehicle.DoesNotExist:
        return {"status_code": 404, "error": "not_found", "message": "Garage vehicle not found or not owned."}
    
    if garage_vehicle.status != GarageVehicleStatus.ACTIVE:
        return {"status_code": 422, "error": "invalid_status", "message": "Vehicle is not active."}
    
    from apps.vehicles.models import PowertrainType
    vehicle_cat = garage_vehicle.vehicle_catalogue
    if vehicle_cat is None:
        return {
            "status_code": 422,
            "error": "ridereveal_unavailable",
            "message": "RideReveal is only available for Carreb catalogue vehicles."
        }
    if vehicle_cat.powertrain_type == PowertrainType.FCEV:
        return {
            "status_code": 422, 
            "error": "ridereveal_unavailable", 
            "message": "RideReveal is not available for hydrogen vehicles at this time."
        }
        
    existing_result = RideRevealResult.objects.filter(
        user=user, garage_vehicle=garage_vehicle).first()
    if existing_result:
        plate_changed = (custom_plate or None) != existing_result.custom_plate
        color_changed = (favorite_color or None) != existing_result.favorite_color
        new_name = (first_name or '').strip() or None
        name_changed = new_name is not None and new_name != existing_result.first_name
        new_photo = None
        photo_changed = False
        if photo_url:
            try:
                new_photo = normalize_photo_url(photo_url)
            except ValueError as exc:
                return {"status_code": 422, "error": "invalid_photo_url",
                        "message": str(exc)}
            photo_changed = new_photo != (existing_result.uploaded_photo.name or None)

        if not (plate_changed or color_changed or name_changed or photo_changed):
            from apps.mygarage.serializers import RideRevealResultSerializer
            return {
                "status_code": 200,
                "already_generated": True,
                "result": RideRevealResultSerializer(existing_result).data
            }

        # Edit path (B-17): apply the new plate/colour/name/photo without
        # consuming a credit. Plate or colour changes alter the generated
        # content, so the profile is regenerated for free; a name-only or
        # photo-only change just re-renders the share card.
        if name_changed:
            existing_result.first_name = new_name
            existing_result.save(update_fields=['first_name'])
        if photo_changed:
            existing_result.uploaded_photo = new_photo
            existing_result.save(update_fields=['uploaded_photo'])
        if plate_changed or color_changed:
            job = RideRevealJob.objects.create(
                user=user,
                garage_vehicle=garage_vehicle,
                custom_plate=custom_plate,
                favorite_color=favorite_color,
                first_name=existing_result.first_name,
                photo_url=new_photo or existing_result.uploaded_photo.name,
                status=RideRevealJobStatus.PENDING
            )
            generate_ridereveal_content.delay(job.id, None)
            return {
                "status_code": 200,
                "job_id": str(job.id),
                "status": "pending",
                "regenerating": True,
                "credits_remaining": _get_or_create_credits(user).credits_available
            }
        from apps.mygarage.share_card import generate_share_card_png
        generate_share_card_png(existing_result)
        from apps.mygarage.serializers import RideRevealResultSerializer
        return {
            "status_code": 200,
            "already_generated": True,
            "result": RideRevealResultSerializer(existing_result).data
        }

    credits = _get_or_create_credits(user)
    is_unlimited = credits.plan == SubscriptionTier.FULL_INSIGHT_PRO

    credit_type = RideRevealCreditType.PLAN_INCLUDED

    with transaction.atomic():
        credits = RideRevealCredit.objects.select_for_update().get(id=credits.id)

        if not is_unlimited:
            # Free-tier sign-up entitlement: exactly one free reveal, consumed
            # here but refunded by the task if generation fails.
            is_free_tier = credits.plan == SubscriptionTier.FREE
            free_available = is_free_tier and not credits.free_reveal_used

            if credits.credits_available <= 0 and not free_available:
                return {
                    "status_code": 402,
                    "error": "insufficient_credits",
                    "credits_available": 0,
                    "purchase_options": {
                        "single": {"price_display": "A$4.99", "credits": 1},
                        "bundle": {"price_display": "A$19.99", "credits": 5}
                    }
                }

            if free_available and credits.credits_available <= 0:
                credit_type = RideRevealCreditType.FREE_SIGNUP
                credits.free_reveal_used = True
                credits.save(update_fields=['free_reveal_used'])
            else:
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
            favorite_color=favorite_color,
            first_name=(first_name or '').strip() or None,
            photo_url=normalize_photo_url(photo_url) if photo_url else None,
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

    if event['type'] in ['payment_intent.succeeded', 'checkout.session.completed', 'invoice.paid', 'invoice.payment_failed', 'customer.subscription.updated', 'customer.subscription.deleted']:
        intent_or_session = event['data']['object']
        if hasattr(intent_or_session, 'to_dict'):
            intent_or_session = intent_or_session.to_dict()
            
        if event['type'] in ['invoice.paid', 'invoice.payment_failed', 'customer.subscription.updated', 'customer.subscription.deleted']:
            # Forward directly to billing handlers without re-verifying signature
            from apps.billing.services import _handle_invoice_paid, _handle_invoice_payment_failed, _handle_subscription_updated, _handle_subscription_deleted
            if event['type'] == 'invoice.paid':
                _handle_invoice_paid(intent_or_session)
            elif event['type'] == 'invoice.payment_failed':
                _handle_invoice_payment_failed(intent_or_session)
            elif event['type'] == 'customer.subscription.updated':
                _handle_subscription_updated(intent_or_session)
            elif event['type'] == 'customer.subscription.deleted':
                _handle_subscription_deleted(intent_or_session)
            return True

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
                from apps.billing.services import _handle_checkout_session_completed, _handle_payment_intent_succeeded
                
                if event['type'] == 'checkout.session.completed':
                    _handle_checkout_session_completed(intent_or_session)
                elif event['type'] == 'payment_intent.succeeded':
                    _handle_payment_intent_succeeded(intent_or_session)
                
                return True
                
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
