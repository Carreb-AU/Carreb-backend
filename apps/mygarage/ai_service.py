import json
import os
from datetime import datetime
from typing import Optional

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


# ---------------------------------------------------------------------------
# Field-level AI estimation for current-vehicle / GVG enrichment (P0.5)
# ---------------------------------------------------------------------------

ENGINE_DISPLACEMENT_PROMPT = """You are a vehicle database assistant. Estimate the engine displacement in litres for the vehicle described.

Vehicle: {year} {make} {model} {variant}

Return ONLY a valid JSON object with this exact schema:
{{
  "engine_l": float or null,  // engine displacement in litres, e.g. 2.0
  "confidence": "high" | "medium" | "low",
  "reasoning": "one short sentence"
}}

If the vehicle is electric (BEV) or hydrogen (FCEV), return null for engine_l. If you are uncertain, use your best estimate and set confidence to low. Do not return any text outside the JSON object."""

ANCAP_RATING_PROMPT = """You are a vehicle safety database assistant. Estimate the ANCAP safety rating for the vehicle described.

Vehicle: {year} {make} {model}

Return ONLY a valid JSON object with this exact schema:
{{
  "ancap_rating": integer or null,  // 1 to 5 stars
  "confidence": "high" | "medium" | "low",
  "reasoning": "one short sentence"
}}

ANCAP ratings did not exist before 1993, so for older vehicles return null. If the exact model-year rating is unknown, use your best estimate and set confidence to low. Do not return any text outside the JSON object."""


def _call_openai_json(prompt: str, model: str = "gpt-4o-mini") -> dict:
    """Call OpenAI with a prompt and return parsed JSON, or {} on failure."""
    if not OPENAI_API_KEY:
        logger.error("OpenAI API key is missing; cannot run field estimation.")
        return {}

    client = openai.OpenAI(api_key=OPENAI_API_KEY, timeout=8.0)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            timeout=8.0,
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        logger.error(f"OpenAI JSON call failed: {e}")
        return {}


def estimate_engine_displacement(make: str, model: str, variant: str, year: int) -> Optional[float]:
    """Return estimated engine displacement in litres, or None."""
    prompt = ENGINE_DISPLACEMENT_PROMPT.format(
        make=make or '',
        model=model or '',
        variant=variant or '',
        year=year or '',
    )
    result = _call_openai_json(prompt)
    engine_l = result.get('engine_l')
    if engine_l is None:
        return None
    try:
        return float(engine_l)
    except (ValueError, TypeError):
        return None


def estimate_ancap_rating(make: str, model: str, year: int) -> Optional[int]:
    """Return estimated ANCAP rating 1-5, or None for pre-ANCAP vehicles."""
    prompt = ANCAP_RATING_PROMPT.format(
        make=make or '',
        model=model or '',
        year=year or '',
    )
    result = _call_openai_json(prompt)
    rating = result.get('ancap_rating')
    if rating is None:
        return None
    try:
        rating = int(rating)
        return rating if 1 <= rating <= 5 else None
    except (ValueError, TypeError):
        return None


def estimate_resale_value(
    driveaway_cents: int,
    year: int,
    current_year: Optional[int] = None,
    retention_rate: float = 0.50,
    powertrain_type: Optional[str] = None,
    brand: Optional[str] = None,
) -> Optional[int]:
    """Return a retention-based 5-year resale estimate in cents, with modifiers.

    Applies EnergyTypeModifier and DepreciationBrandModifier multipliers to
    the base retention curve (Spec §3.5).
    """
    from apps.vehicles.services.gvg_import import (
        _get_energy_modifier,
        _get_brand_modifier,
    )

    if not driveaway_cents or not year:
        return None
    if current_year is None:
        current_year = datetime.now().year

    energy_mod = _get_energy_modifier(powertrain_type)
    brand_mod = _get_brand_modifier(brand)

    retention_mult = (
        retention_rate
        * (energy_mod.retention_multiplier if energy_mod else 1.0)
        * (brand_mod.retention_multiplier if brand_mod else 1.0)
    )
    resale_mult = (
        (energy_mod.resale_value_multiplier if energy_mod else 1.0)
        * (brand_mod.resale_value_multiplier if brand_mod else 1.0)
    )

    age = max(0, current_year - year)
    # Avoid compounding to zero for very old cars; floor at 5% of driveaway.
    value_cents = int(
        driveaway_cents
        * max(0.05, retention_mult ** age)
        * resale_mult
    )
    return value_cents
