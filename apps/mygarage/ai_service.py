import json
import os
import openai
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Fallback: assume the key is in env or settings
OPENAI_API_KEY = getattr(settings, 'OPENAI_API_KEY', os.environ.get('OPENAI_API_KEY'))

SYSTEM_PROMPT = """You are a vehicle search parameter extractor. 
Extract structured search parameters from the user's natural language vehicle query. 
Return ONLY a valid JSON object with any applicable fields from this schema: 
{ budget_min: integer (AUD), 
  budget_max: integer (AUD), 
  powertrain_types: array of enum [petrol, diesel, mild_hybrid, hybrid, phev, bev, fcev], 
  num_seats_min: integer, 
  body_styles: array of enum [sedan, suv, hatchback, wagon, ute, van, coupe, convertible], 
  fcai_categories: array of strings, 
  core_rating_min: float, 
  annual_km: integer, 
  ancap_rating_min: integer (1-5),
  primary_use: enum [city_commuter, family_car, mixed_use, long_distance, work_vehicle] }. 
Only include fields you can extract with reasonable confidence. Do not include fields not mentioned or implied. Do not return vehicle names or recommendations. Return nothing except the JSON object."""

def extract_search_parameters(query: str):
    """
    Calls OpenAI to extract structured search parameters from a natural language query.
    Returns (is_available, parsed_filters)
    """
    if not OPENAI_API_KEY:
        logger.error("OpenAI API key is missing.")

        return False, {}

    
    client = openai.OpenAI(api_key=OPENAI_API_KEY, timeout=8.0)
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query}
            ],
            response_format={"type": "json_object"},
            timeout=8.0
        )
        content = response.choices[0].message.content
        filters = json.loads(content)
        return True, filters
    except Exception as e:
        logger.error(f"AI Smart Match extraction failed: {e}")
        return False, {}

def build_recommendation_reason(interpreted_filters, vehicle):
    """
    Build a deterministic plain English sentence based on how the vehicle matched the filters.
    """
    reasons = []
    
    pt_filter = interpreted_filters.get('powertrain_types')
    if pt_filter and getattr(vehicle, 'powertrain_type', None):
        pts = pt_filter if isinstance(pt_filter, list) else [pt_filter]
        if vehicle.powertrain_type.lower() in [p.lower() for p in pts]:
            if vehicle.powertrain_type.lower() == 'bev':
                reasons.append("Battery electric")
            else:
                reasons.append(f"{vehicle.powertrain_type.title().replace('_', ' ')}")
                
 
    if interpreted_filters.get('budget_max') or interpreted_filters.get('budget_min'):
        reasons.append("matches your budget")
        
    
    if interpreted_filters.get('core_rating_min'):
        reasons.append(f"{interpreted_filters['core_rating_min']}★ CORE Rating")
        
    
    use_case = interpreted_filters.get('primary_use')
    if use_case:
        reasons.append(f"suits your {use_case.replace('_', ' ')} use case")
    elif interpreted_filters.get('body_styles') and getattr(vehicle, 'body_style', None):
        bss = interpreted_filters['body_styles'] if isinstance(interpreted_filters['body_styles'], list) else [interpreted_filters['body_styles']]
        if vehicle.body_style.lower() in [b.lower() for b in bss]:
            reasons.append(f"{vehicle.body_style.title()}")
            
    if interpreted_filters.get('num_seats_min'):
        reasons.append(f"{interpreted_filters['num_seats_min']}+ seats")

    if not reasons:
        if getattr(vehicle, 'fcai_category', None):
            return f"Great option in the {vehicle.fcai_category} class"
        return "Matches your search criteria"
        

    if len(reasons) == 1:
        prefix = reasons[0]
    else:
        prefix = ", ".join(reasons[:-1]) + f" and {reasons[-1]}"
        
    if prefix:
        prefix = prefix[0].upper() + prefix[1:]
    
    if getattr(vehicle, 'fcai_category', None):
        return f"{prefix} - great option in the {vehicle.fcai_category} class"
    return prefix
