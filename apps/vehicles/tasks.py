from celery import shared_task
import logging

logger = logging.getLogger(__name__)

@shared_task
def emit_analytics_event(user_id: str, event_name: str, event_data: dict):
    """
    Emits an analytics event if the user has consented.
    In a real-world scenario, this might push to Segment, Mixpanel, etc.
    """
    logger.info(f"Analytics Event [{event_name}] for user {user_id}: {event_data}")
    

@shared_task
def process_vehicle_excel_upload(file_path):
    import pandas as pd
    from django.utils import timezone
    from .models import Vehicle

    try:
        df = pd.read_excel(file_path)
        
        vehicles_data = {}
        
        for _, row in df.iterrows():
            make = str(row.get('Make', '')).strip()
            model = str(row.get('Model', '')).strip()
            variant = str(row.get('Variant', '')).strip()
            year = row.get('Year')
            
            if pd.isna(year):
                continue
                
            year = int(year)
            
            key = (make, model, variant, year)
            
            state = str(row.get('State', '')).strip()
            driveaway = row.get('Driveaway Price ($)')
            cost_5yr = row.get('5yr Cost of Ownership ($)')
            
            if pd.isna(driveaway):
                driveaway = 0
            if pd.isna(cost_5yr):
                cost_5yr = 0
                
            if key not in vehicles_data:
                powertrain = str(row.get('Fuel Type', 'petrol')).lower()
                if powertrain not in ['petrol', 'diesel', 'mild_hybrid', 'hybrid', 'phev', 'bev', 'fcev']:
                    powertrain = 'petrol'
                    
                vehicles_data[key] = {
                    'brand': make,
                    'model': model,
                    'variant': variant,
                    'year': year,
                    'powertrain_type': powertrain,
                    'body_style': str(row.get('Body Type', '')).strip(),
                    'fcai_category': str(row.get('Category', '')).strip(),
                    'fuel_consumption_per_100km': float(row.get('Fuel Eff (L/100km)')) if not pd.isna(row.get('Fuel Eff (L/100km)')) else None,
                    'tailpipe_co2_g_per_km': float(row.get('CO2 Tailpipe (g/km)')) if not pd.isna(row.get('CO2 Tailpipe (g/km)')) else None,
                    'wltp_range_km': float(row.get('Range (km)')) if not pd.isna(row.get('Range (km)')) else None,
                    'driveaway_price_by_state': {},
                    'total_5yr_cost_of_ownership_by_state': {}
                }
                
            # Add state pricing
            if state:
                vehicles_data[key]['driveaway_price_by_state'][state] = int(driveaway * 100) # cents
                vehicles_data[key]['total_5yr_cost_of_ownership_by_state'][state] = int(cost_5yr * 100) # cents

        # Now create or update the DB
        now_iso = timezone.now().isoformat()
        
        for (make, model, variant, year), data in vehicles_data.items():
            # Set provenance for the new data
            provenance = {
                "source_category": "carreb-core-dump",
                "retrieved_at": now_iso
            }
            
            Vehicle.objects.update_or_create(
                brand=make,
                model=model,
                variant=variant,
                year=year,
                defaults={
                    'powertrain_type': data['powertrain_type'],
                    'body_style': data['body_style'],
                    'fcai_category': data['fcai_category'] if data['fcai_category'] != 'nan' else '',
                    'fuel_consumption_per_100km': data['fuel_consumption_per_100km'],
                    'tailpipe_co2_g_per_km': data['tailpipe_co2_g_per_km'],
                    'wltp_range_km': data['wltp_range_km'],
                    'driveaway_price_by_state': data['driveaway_price_by_state'],
                    'total_5yr_cost_of_ownership_by_state': data['total_5yr_cost_of_ownership_by_state'],
                    'provenance': provenance,
                    'num_seats': 5, # default
                    'annual_km_default': 13300 # default
                }
            )
        logger.info(f"Successfully processed vehicle upload from {file_path}")
    except Exception as e:
        logger.error(f"Failed to process vehicle upload from {file_path}: {e}")

