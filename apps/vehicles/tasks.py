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
        xls = pd.ExcelFile(file_path)
        sheet_names = xls.sheet_names
        
        dfs_to_process = []
        if 'v6.3.4 Data' in sheet_names or 'New Vehicles FY26' in sheet_names:
            if 'v6.3.4 Data' in sheet_names:
                dfs_to_process.append(pd.read_excel(xls, sheet_name='v6.3.4 Data'))
            if 'New Vehicles FY26' in sheet_names:
                dfs_to_process.append(pd.read_excel(xls, sheet_name='New Vehicles FY26'))
        else:
            # Fallback to the first sheet for old files
            dfs_to_process.append(pd.read_excel(xls, sheet_name=0))
            
        if not dfs_to_process:
            raise ValueError("No valid data sheets found.")
            
        df = pd.concat(dfs_to_process, ignore_index=True)
        
        coo_df = None
        if 'COO_Component_Breakdown' in sheet_names:
            coo_df = pd.read_excel(xls, sheet_name='COO_Component_Breakdown')
            
        vehicles_data = {}
        
        for _, row in df.iterrows():
            make = str(row.get('Make', '')).strip()
            model = str(row.get('Model', '')).strip()
            variant = str(row.get('Variant', '')).strip()
            year = row.get('Year')
            
            if pd.isna(year):
                continue
                
            try:
                year = int(year)
            except (ValueError, TypeError):
                continue
            
            key = (make, model, variant, year)
            
            state = str(row.get('State', '')).strip()
            driveaway = row.get('Driveaway Price ($)')
            
            # Handle old and new column names
            cost_5yr = row.get('Mode 5yr COO ($)')
            if pd.isna(cost_5yr) and '5yr Cost of Ownership ($)' in df.columns:
                cost_5yr = row.get('5yr Cost of Ownership ($)')
            
            if pd.isna(driveaway):
                driveaway = 0
            if pd.isna(cost_5yr):
                cost_5yr = 0
                
            if key not in vehicles_data:
                powertrain = str(row.get('Fuel Type', 'petrol')).lower()
                if powertrain not in ['petrol', 'diesel', 'mild_hybrid', 'hybrid', 'phev', 'bev', 'fcev']:
                    powertrain = 'petrol'
                    
                fcai_category = str(row.get('fcai_category', row.get('Category', ''))).strip()
                if fcai_category == 'nan':
                    fcai_category = ''
                    
                fuel_eff = row.get('Fuel Eff (L/100km)')
                co2 = row.get('CO2 Tailpipe (g/km)')
                range_km = row.get('Range (km)')
                
                vehicles_data[key] = {
                    'brand': make,
                    'model': model,
                    'variant': variant,
                    'year': year,
                    'powertrain_type': powertrain,
                    'body_style': str(row.get('Body Type', '')).strip(),
                    'fcai_category': fcai_category,
                    'fuel_consumption_per_100km': float(fuel_eff) if not pd.isna(fuel_eff) else None,
                    'tailpipe_co2_g_per_km': float(co2) if not pd.isna(co2) else None,
                    'wltp_range_km': float(range_km) if not pd.isna(range_km) else None,
                    'driveaway_price_by_state': {},
                    'total_5yr_cost_of_ownership_by_state': {},
                    'ctp_by_state': {},
                    'insurance_estimate_by_state': {},
                    'registration_by_state': {}
                }
                
            if state and str(state) != 'nan':
                try:
                    vehicles_data[key]['driveaway_price_by_state'][state] = int(float(driveaway) * 100) # cents
                except (ValueError, TypeError):
                    pass
                try:
                    vehicles_data[key]['total_5yr_cost_of_ownership_by_state'][state] = int(float(cost_5yr) * 100) # cents
                except (ValueError, TypeError):
                    pass

        if coo_df is not None:
            for _, row in coo_df.iterrows():
                make = str(row.get('Make', '')).strip()
                model = str(row.get('Model', '')).strip()
                variant = str(row.get('Variant', '')).strip()
                year = row.get('Year')
                
                if pd.isna(year):
                    continue
                try:
                    year = int(year)
                except (ValueError, TypeError):
                    continue
                key = (make, model, variant, year)
                state = str(row.get('State', '')).strip()
                
                if key in vehicles_data and state and str(state) != 'nan':
                    ctp = row.get('ctp_pa')
                    insurance = row.get('comprehensive_pa')
                    rego = row.get('registration_pa')
                    
                    if not pd.isna(ctp):
                        try:
                            vehicles_data[key]['ctp_by_state'][state] = int(float(ctp) * 100)
                        except (ValueError, TypeError):
                            pass
                    if not pd.isna(insurance):
                        try:
                            vehicles_data[key]['insurance_estimate_by_state'][state] = int(float(insurance) * 100)
                        except (ValueError, TypeError):
                            pass
                    if not pd.isna(rego):
                        try:
                            vehicles_data[key]['registration_by_state'][state] = int(float(rego) * 100)
                        except (ValueError, TypeError):
                            pass

        # Now create or update the DB
        now_iso = timezone.now().isoformat()
        
        for (make, model, variant, year), data in vehicles_data.items():
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
                    'fcai_category': data['fcai_category'],
                    'fuel_consumption_per_100km': data['fuel_consumption_per_100km'],
                    'tailpipe_co2_g_per_km': data['tailpipe_co2_g_per_km'],
                    'wltp_range_km': data['wltp_range_km'],
                    'driveaway_price_by_state': data['driveaway_price_by_state'],
                    'total_5yr_cost_of_ownership_by_state': data['total_5yr_cost_of_ownership_by_state'],
                    'ctp_by_state': data['ctp_by_state'],
                    'insurance_estimate_by_state': data['insurance_estimate_by_state'],
                    'registration_by_state': data['registration_by_state'],
                    'provenance': provenance,
                    'num_seats': 5, # default
                    'annual_km_default': 13300 # default
                }
            )
        logger.info(f"Successfully processed vehicle upload from {file_path}")
    except Exception as e:
        logger.error(f"Failed to process vehicle upload from {file_path}: {e}")

