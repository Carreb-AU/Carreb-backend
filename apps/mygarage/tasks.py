import json
import logging
import openai
from django.conf import settings
from django.utils import timezone
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from apps.mygarage.models import RideRevealJob, RideRevealJobStatus, RideRevealResult, RideRevealCredit
from apps.vehicles.tasks import emit_analytics_event

logger = logging.getLogger(__name__)

OPENAI_API_KEY = getattr(settings, 'OPENAI_API_KEY', None)

SYSTEM_PROMPT = """Generate a RideReveal personality profile with these exact fields:
archetype_name: a 2-3 word personality archetype (e.g. Steady Optimist, Bold Pioneer)
archetype_tagline: a short punchy phrase
self_insight_text: 2-3 sentences exploring the psychological motivations behind choosing this vehicle, based on published research in consumer behaviour and identity signalling
social_perception_text: 2-3 sentences about how others might perceive this vehicle choice
did_you_know_fact: 1 interesting fact about this vehicle type or ownership profile
share_caption: max 280 characters, suitable for social media
All outputs are for entertainment and educational purposes only. Do not include financial advice, purchase recommendations, statements of fact about actual vehicle performance, or emissions claims. Return ONLY a valid JSON object with these six fields. No preamble. No markdown."""

@shared_task(time_limit=30, soft_time_limit=25)
def generate_ridereveal_content(job_id, credit_type):
    try:
        job = RideRevealJob.objects.get(id=job_id)
    except RideRevealJob.DoesNotExist:
        logger.error(f"RideRevealJob {job_id} not found.")
        return

    job.status = RideRevealJobStatus.PROCESSING
    job.save()

    start_time = timezone.now()
    error_msg = None

    try:
        if not OPENAI_API_KEY:
            raise Exception("OpenAI API key is missing.")

        client = openai.OpenAI(api_key=OPENAI_API_KEY, timeout=20.0)

        vehicle = job.garage_vehicle.vehicle_catalogue
        user = job.user
        priority_state = getattr(user, 'priority_state', None)
        
        from apps.vehicles.services.rating_engine import calculate_core_rating
        from apps.mygarage.models import VehicleOverride
        
        cv = getattr(user, 'current_vehicle', None)
        state = cv.state if cv and cv.state else 'NSW'
        priority = priority_state.priority_slider_position if priority_state else 3
        mode = priority_state.active_core_mode if priority_state else 'pure_cost'
        
        overrides_qs = VehicleOverride.objects.filter(user=user, garage_vehicle=job.garage_vehicle)
        user_inputs = {o.field_name: o.override_value for o in overrides_qs}
        
        engine_data = calculate_core_rating(vehicle, state, priority, mode, user_inputs)
        core_rating = engine_data.get('core_rating')
        band_name = engine_data.get('band_name', 'Unknown')
        
        priority_label = "balanced"
        if priority_state:
            val = priority_state.priority_slider_position
            if val <= 2:
                priority_label = "cost-focused"
            elif val >= 4:
                priority_label = "environmentally focused"
                
        custom_plate_info = f"Custom Plate: {job.custom_plate}" if job.custom_plate else ""
        
        user_prompt = f"""
Vehicle: {vehicle.brand} {vehicle.model} {vehicle.year} {vehicle.variant}
Powertrain: {vehicle.powertrain_type}
CORE Rating: {core_rating}
Band Name: {band_name}
User Priority: {priority_label}
{custom_plate_info}
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            timeout=20.0
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)
        
        required_fields = [
            'archetype_name', 'archetype_tagline', 'self_insight_text',
            'social_perception_text', 'did_you_know_fact', 'share_caption'
        ]
        
        for field in required_fields:
            if field not in data or not data[field]:
                raise Exception(f"Missing required field: {field}")
                
        duration_ms = int((timezone.now() - start_time).total_seconds() * 1000)
        
        result = RideRevealResult.objects.create(
            user=job.user,
            garage_vehicle=job.garage_vehicle,
            vehicle_catalogue=vehicle,
            custom_plate=job.custom_plate,
            archetype_name=data['archetype_name'],
            archetype_tagline=data['archetype_tagline'],
            self_insight_text=data['self_insight_text'],
            social_perception_text=data['social_perception_text'],
            did_you_know_fact=data['did_you_know_fact'],
            share_caption=data['share_caption'],
            disclaimer="for entertainment and educational purposes only",
            ai_model_version="gpt-4o-mini",
            generation_duration_ms=duration_ms,
            credit_type=credit_type
        )
        
        job.status = RideRevealJobStatus.COMPLETE
        job.result = result
        job.completed_at = timezone.now()
        job.save()

        emit_analytics_event.delay(
            user_id=job.user.id,
            event_name='ridereveal_generated',
            event_data={
                'powertrain_type': vehicle.powertrain_type,
                'band_name': getattr(vehicle, 'band_name', None),
                'credit_type': credit_type
            }
        )
        return

    except SoftTimeLimitExceeded:
        error_msg = "Task timeout"
    except Exception as e:
        logger.error(f"RideReveal generation failed: {e}")
        error_msg = "AI generation failed"

    # Handle failure
    job.status = RideRevealJobStatus.FAILED
    job.error_message = error_msg
    job.completed_at = timezone.now()
    job.save()
    
    # Refund credit
    try:
        credits = RideRevealCredit.objects.get(user=job.user)
        credits.credits_used = max(0, credits.credits_used - 1)
        credits.save()
    except RideRevealCredit.DoesNotExist:
        pass
        
    vehicle = job.garage_vehicle.vehicle_catalogue
    emit_analytics_event.delay(
        user_id=job.user.id,
        event_name='ridereveal_generation_failed',
        event_data={
            'powertrain_type': vehicle.powertrain_type
        }
    )

@shared_task
def annual_credit_reset():
    from apps.users.models import SubscriptionTier
    today = timezone.now().date()
    
    credits_qs = RideRevealCredit.objects.filter(
        plan=SubscriptionTier.CORE_ADVANTAGE,
        period_end__lte=today
    )
    
    for credits in credits_qs:
        credits.credits_included = 4
        # unused included credits do not carry over, which happens naturally since credits_included is reset
        # wait, credits_used could be high, we need to reset credits_used?
        # If they had 4 included, and 2 purchased, and used 3. 
        # credits_included = 4, credits_purchased = 2, credits_used = 3. available = 3.
        # But wait, credits_used tracks ALL credits used ever. 
        # If we reset credits_included, and leave credits_used, they will be negative!
        # "credits_available (computed on read: included + purchased - used, minimum 0)"
        # If we reset credits_included to 4, we must adjust credits_used so they only lose unused INCLUDED credits.
        # Example: start with 4 inc, 2 pur, used 3 (so 1 inc remaining, 2 pur).
        # We reset inc to 4. They should now have 4 inc, 2 pur, used 0? 
        # No, purchased credits carry over. So available should be 4 + 2 = 6.
        # So we should set credits_used to 0, and credits_purchased to the remaining purchased credits.
        # Wait, if they used 5 credits (4 included, 1 purchased), remaining purchased is 1.
        # We can just do:
        # remaining_purchased = max(0, credits_purchased - max(0, credits_used - credits_included))
        # credits_included = 4
        # credits_purchased = remaining_purchased
        # credits_used = 0
        
        remaining_purchased = max(0, credits.credits_purchased - max(0, credits.credits_used - credits.credits_included))
        credits.credits_included = 4
        credits.credits_purchased = remaining_purchased
        credits.credits_used = 0
        
        credits.period_start = today
        credits.period_end = today + timezone.timedelta(days=365)
        credits.save()
