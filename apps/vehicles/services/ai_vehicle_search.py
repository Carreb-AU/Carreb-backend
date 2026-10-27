"""AI (Grok/xAI) vehicle-spec lookup for cars missing from the database.

Pipeline design (token economy):
- The AI API is called ONLY from the explicit user action endpoint
  (POST /api/current-vehicle/ai-search/) — never from type-ahead keystrokes.
- Every distinct (normalised) query is answered by Grok exactly once and the
  parsed candidates are stored in AIVehicleEntry. Repeat searches are served
  from that table (cache) with search_count incremented, so tokens are spent
  once per distinct query, not once per user request.
- When a user picks a candidate as their current vehicle, the row is linked
  from CurrentVehicle and selected_count is incremented — no new API call.

The stored rows mirror VehicleIdentity field names, so they can be wrapped by
VehicleLike / cost_gvg_current_vehicle and costed like a GVG current car
(filling the gap the old manual-entry flow left: no emissions/consumption).
"""
import json
import logging
import re

from django.conf import settings
from django.db import models as django_models

from apps.vehicles.models import AIVehicleEntry, PowertrainType
from apps.vehicles.services.image_ai import GROK_API_KEY, xai_client

logger = logging.getLogger(__name__)

XAI_CHAT_MODEL = getattr(settings, 'XAI_CHAT_MODEL', 'grok-4.3')

MAX_CANDIDATES = 3

SEARCH_PROMPT = """You are an Australian vehicle database assistant. A user could not find their car in our database. From their search text, identify the real Australian-market vehicle(s) they mean and provide specifications.

User search: "{query}"

Return ONLY a valid JSON object, no markdown fences, no extra text:
{{
  "vehicles": [
    {{
      "year": integer or null,
      "make": string,
      "model": string,
      "variant": string or "",
      "body_style": one of hatchback|sedan|suv|wagon|ute|van|coupe|convertible|people mover or "",
      "powertrain": one of petrol|diesel|mild_hybrid|hybrid|phev|bev|fcev,
      "fuel_type_raw": string e.g. "Petrol", "Unleaded", "Diesel", "Electric", "Plug-in Hybrid",
      "drive": string e.g. "FWD", "RWD", "AWD" or "",
      "engine_l": float litres or null,
      "battery_kwh": float or null,
      "num_seats": integer or null,
      "ancap_safety_rating": integer 1-5 or null,
      "fuel_consumption_l_100km": float combined or null,
      "electricity_consumption_wh_per_km": float or null,
      "electric_range_km": float or null,
      "tailpipe_co2_g_per_km": float combined or null,
      "fcai_category": one of Light|Small|Medium|Large|Upper Large|Small SUV|Medium SUV|Large SUV|Upper Large SUV|People Mover|Ute|Van|Light Commercial or "",
      "driveaway_price_aud": integer Australian driveaway/RRP dollars or null
    }}
  ]
}}

Rules:
- Return 1 to {max} candidates, most likely match first. If the search text is ambiguous (e.g. a long-running nameplate), return the plausible distinct variants.
- Only real vehicles sold in Australia. Never invent specifications — use null when unknown.
- fuel_consumption_l_100km is for petrol/diesel/hybrid/PHEV; electricity_consumption_wh_per_km and electric_range_km for BEV/PHEV.
- For PHEV provide both fuel consumption and electric range/consumption if known.
- For fuel_consumption_l_100km and tailpipe_co2_g_per_km, provide your best-estimate combined ADR figures even for older or obscure cars — only use null if you have no reasonable estimate at all.
- fcai_category: pick the closest FCAI size/shape segment for the Australian market (e.g. a Toyota Corolla is "Small", a Mazda CX-5 is "Medium SUV", a Holden Commodore is "Large", a Toyota HiLux is "Ute")."""


class AIVehicleSearchError(Exception):
    """Raised when the Grok lookup fails (no key, network, credits, bad response)."""


def normalize_query(query: str) -> str:
    return ' '.join((query or '').casefold().split())[:300]


def search_ai_vehicles(query: str, user=None) -> tuple[list[AIVehicleEntry], bool]:
    """
    Return (entries, from_cache) for a normalised query. Serves repeats from
    the AIVehicleEntry cache; otherwise calls Grok once and stores candidates.
    """
    norm = normalize_query(query)
    if len(norm) < 3:
        raise AIVehicleSearchError("Query too short — at least 3 characters.")

    cached_qs = AIVehicleEntry.objects.filter(search_query=norm)
    if cached_qs.exists():
        cached_qs.update(search_count=django_models.F('search_count') + 1)
        return list(cached_qs), True

    candidates = _fetch_from_grok(norm)
    if not candidates:
        raise AIVehicleSearchError("The AI could not identify a matching vehicle.")

    entries = [
        AIVehicleEntry.objects.create(search_query=norm, created_by=user, **c)
        for c in candidates
    ]
    logger.info("AI vehicle search %r: stored %d candidates", norm, len(entries))
    return entries, False


def _fetch_from_grok(query: str) -> list[dict]:
    if not GROK_API_KEY:
        raise AIVehicleSearchError("AI search is not configured (missing API key).")

    client = xai_client()
    try:
        response = client.chat.completions.create(
            model=XAI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": "You respond only with valid JSON."},
                {"role": "user", "content": SEARCH_PROMPT.format(query=query, max=MAX_CANDIDATES)},
            ],
            response_format={"type": "json_object"},
            timeout=60,
        )
        raw = json.loads(response.choices[0].message.content)
    except AIVehicleSearchError:
        raise
    except Exception as exc:
        logger.exception("Grok vehicle-spec lookup failed for %r", query)
        raise AIVehicleSearchError(f"AI lookup failed: {exc}") from exc

    vehicles = raw.get('vehicles') or []
    if not isinstance(vehicles, list):
        raise AIVehicleSearchError("AI returned an unexpected response shape.")
    return [_normalize_candidate(v, raw) for v in vehicles[:MAX_CANDIDATES]
            if isinstance(v, dict) and v.get('make') and v.get('model')]


_POWERTRAIN_MAP = {
    'petrol': PowertrainType.PETROL,
    'gasoline': PowertrainType.PETROL,
    'unleaded': PowertrainType.PETROL,
    'diesel': PowertrainType.DIESEL,
    'mild_hybrid': PowertrainType.MILD_HYBRID,
    'mild hybrid': PowertrainType.MILD_HYBRID,
    'mhev': PowertrainType.MILD_HYBRID,
    'hybrid': PowertrainType.HYBRID,
    'hev': PowertrainType.HYBRID,
    'phev': PowertrainType.PHEV,
    'plug-in hybrid': PowertrainType.PHEV,
    'plug in hybrid': PowertrainType.PHEV,
    'bev': PowertrainType.BEV,
    'electric': PowertrainType.BEV,
    'ev': PowertrainType.BEV,
    'battery electric': PowertrainType.BEV,
    'fcev': PowertrainType.FCEV,
    'hydrogen': PowertrainType.FCEV,
}


def _to_float(val):
    try:
        if val is None or val == '':
            return None
        return round(float(val), 2)
    except (ValueError, TypeError):
        return None


def _to_int(val):
    try:
        if val is None or val == '':
            return None
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _normalize_candidate(v: dict, raw: dict) -> dict:
    pt_key = re.sub(r'[^a-z0-9]+', ' ', str(v.get('powertrain') or '').casefold()).strip()
    powertrain = _POWERTRAIN_MAP.get(pt_key, PowertrainType.PETROL)
    price_aud = _to_int(v.get('driveaway_price_aud'))
    return {
        'make': str(v.get('make')).strip()[:100],
        'model': str(v.get('model')).strip()[:100],
        'year': _to_int(v.get('year')),
        'variant': str(v.get('variant') or '').strip()[:255],
        'body_style': str(v.get('body_style') or '').strip()[:100],
        'powertrain_type': powertrain,
        'fuel_type_raw': str(v.get('fuel_type_raw') or '').strip()[:100],
        'drive': str(v.get('drive') or '').strip()[:50],
        'engine_l': _to_float(v.get('engine_l')),
        'battery_kwh': _to_float(v.get('battery_kwh')),
        'num_seats': _to_int(v.get('num_seats')),
        'ancap_safety_rating': _to_int(v.get('ancap_safety_rating')),
        'fuel_consumption_combined_l_100km': _to_float(v.get('fuel_consumption_l_100km')),
        'electricity_consumption_wh_per_km': _to_float(v.get('electricity_consumption_wh_per_km')),
        'electric_range_km': _to_float(v.get('electric_range_km')),
        'tailpipe_co2_g_per_km': _to_float(v.get('tailpipe_co2_g_per_km')),
        'fcai_category': str(v.get('fcai_category') or '').strip()[:100],
        'driveaway_price_estimate': price_aud * 100 if price_aud else None,
        'raw_response': {'candidate': v, 'full_response': raw},
        'provenance': {
            'source': 'ai_vehicle_search',
            'source_dataset': 'ai-grok',
        },
    }
