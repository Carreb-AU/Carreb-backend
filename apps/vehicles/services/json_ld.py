"""
JSON-LD structured data builder for vehicle detail pages (GEO Brief §5.1).

Outputs the approved schema.org/Car shape with the ACL envelope:
- ratingValue is CORE rating on a 0.0–5.0 scale.
- bestRating is always 5.
- Cost figures carry an "estimated / indicative" marker via priceValidUntil
  or are omitted if the vehicle has no scored data.
"""
from typing import Optional, Dict, Any
from urllib.parse import urljoin

from django.conf import settings
from apps.config.models import SiteConfig
from apps.vehicles.models import Vehicle, PowertrainType


def _state_for_request(request=None) -> str:
    if request:
        state = (request.query_params.get('state') or request.headers.get('X-State') or 'NSW').upper()
        return state if state in {'NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT'} else 'NSW'
    return 'NSW'


def _canonical_host() -> str:
    try:
        return SiteConfig.get().canonical_host.rstrip('/')
    except Exception:
        return 'https://www.carreb.com.au'


def _vehicle_url(vehicle: Vehicle) -> str:
    """Return the canonical URL for a vehicle detail page.

    The slug pattern is configurable via settings.VEHICLE_URL_PATTERN.
    Defaults to /cars/{make}/{model}/{year}/{variant}/ until the canonical
    slug decision is finalised.
    """
    pattern = getattr(settings, 'VEHICLE_URL_PATTERN', '/cars/{make}/{model}/{year}/{variant}/')
    make = (getattr(vehicle, 'brand', None) or getattr(vehicle, 'make', '')).lower().replace(' ', '-')
    model = (getattr(vehicle, 'model', '') or '').lower().replace(' ', '-')
    variant = (getattr(vehicle, 'variant', '') or '').lower().replace(' ', '-')
    year = getattr(vehicle, 'year', '')
    path = pattern.format(
        make=make,
        model=model,
        year=year,
        variant=variant,
        slug=f"{make}-{model}-{year}-{variant}",
    )
    return urljoin(_canonical_host() + '/', path.lstrip('/'))


def _driveaway_price(vehicle: Vehicle, state: str) -> Optional[int]:
    prices = getattr(vehicle, 'driveaway_price_by_state', None) or {}
    return prices.get(state.upper())


def _fuel_type(vehicle: Vehicle) -> Optional[str]:
    mapping = {
        PowertrainType.PETROL: 'Petrol',
        PowertrainType.DIESEL: 'Diesel',
        PowertrainType.MILD_HYBRID: 'Petrol',
        PowertrainType.HYBRID: 'Hybrid',
        PowertrainType.PHEV: 'Plug-in Hybrid',
        PowertrainType.BEV: 'Electric',
        PowertrainType.FCEV: 'Hydrogen',
    }
    return mapping.get(vehicle.powertrain_type)


def build_car_json_ld(vehicle: Vehicle, request=None) -> Dict[str, Any]:
    """Build schema.org/Car JSON-LD for a Carreb catalogue vehicle."""
    state = _state_for_request(request)

    data: Dict[str, Any] = {
        '@context': 'https://schema.org',
        '@type': 'Car',
        'name': str(vehicle),
        'brand': {
            '@type': 'Brand',
            'name': getattr(vehicle, 'brand', None) or getattr(vehicle, 'make', ''),
        },
        'model': getattr(vehicle, 'model', ''),
        'vehicleConfiguration': getattr(vehicle, 'variant', ''),
        'productionDate': str(getattr(vehicle, 'year', '')) if getattr(vehicle, 'year', None) else None,
        'bodyType': getattr(vehicle, 'body_style', '') or None,
        'fuelType': _fuel_type(vehicle),
        'url': _vehicle_url(vehicle),
    }

    # Engine
    if getattr(vehicle, 'engine_l', None):
        data['vehicleEngine'] = {
            '@type': 'EngineSpecification',
            'engineDisplacement': {
                '@type': 'QuantitativeValue',
                'value': vehicle.engine_l,
                'unitCode': 'LTR',
            },
        }

    # Fuel / electricity consumption
    fuel = getattr(vehicle, 'fuel_consumption_per_100km', None)
    elec = getattr(vehicle, 'electricity_consumption_per_100km', None)
    if fuel:
        data['fuelConsumption'] = {
            '@type': 'QuantitativeValue',
            'value': fuel,
            'unitCode': 'L/100km',
        }
    elif elec:
        data['fuelConsumption'] = {
            '@type': 'QuantitativeValue',
            'value': elec,
            'unitCode': 'kWh/100km',
        }

    # Emissions
    co2 = getattr(vehicle, 'tailpipe_co2_g_per_km', None)
    if co2 is not None:
        data['emissionsCO2'] = {
            '@type': 'QuantitativeValue',
            'value': co2,
            'unitCode': 'G/KM',
        }

    # Image
    image = getattr(vehicle, 'image_url', None)
    if image:
        data['image'] = image

    # Aggregate rating: CORE is /5.
    rating = getattr(vehicle, 'core_rating', None)
    if rating is not None:
        data['aggregateRating'] = {
            '@type': 'AggregateRating',
            'ratingValue': float(rating),
            'bestRating': 5.0,
            'worstRating': 1.0,
            'reviewCount': 1,
        }

    # Offers / pricing (state-specific driveaway)
    price = _driveaway_price(vehicle, state)
    if price:
        data['offers'] = {
            '@type': 'Offer',
            'priceCurrency': 'AUD',
            'price': round(price / 100, 2),
            'availability': 'https://schema.org/InStock',
            'description': 'Estimated driveaway price. Includes on-road costs and state-specific charges.',
        }

    # Remove None values to keep output clean.
    return {k: v for k, v in data.items() if v is not None}
