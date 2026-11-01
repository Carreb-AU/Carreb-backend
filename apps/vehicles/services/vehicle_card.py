"""Canonical full-field vehicle card with per-field provenance.

Every search surface (vehicle lookup, AI search, Smart Car Finder, AI Smart
Match, My Garage, Current Vehicle, public vehicle API) answers with the same
complete vehicle schema, built here. No surface hand-picks a subset of fields
any more — the card always carries every column of the underlying record,
and each field's origin is declared in ``field_sources``:

  "db"      — actual database value (catalogue, GVG or AI-search row)
  "default" — sheet-derived assumption/default (category cost defaults,
              nearest-year catalogue price)
  "ai"      — AI-estimated value (Grok spec estimator or AI-search result)
  null      — genuinely unknown; the field is still present in the response

Fallback order for every field: database value → sheet assumption/default →
AI estimate. Fields are never omitted just because their value is null.
"""
import logging
import re
from typing import Any, Optional

from django.core.cache import cache

from apps.vehicles.models import (
    AIVehicleEntry,
    CategoryCostDefault,
    FCAICategoryRegistry,
    Vehicle,
    VehicleIdentity,
)
from apps.vehicles.services.core_dial import AU_STATES

logger = logging.getLogger(__name__)

ESTIMATE_CACHE_TTL = 60 * 60 * 24 * 30  # 30 days

# Unified response schema: every key is ALWAYS present in the card.
CARD_FIELDS = (
    # identity
    'id', 'source', 'name',
    'make', 'model', 'year', 'variant', 'body_style', 'powertrain_type',
    'fuel_type_raw', 'drive', 'transmission', 'num_seats', 'doors',
    'fcai_category', 'fcai_broad', 'test_cycle',
    # technical
    'engine_l', 'battery_kwh', 'ancap_safety_rating',
    'tow_braked_kg', 'tow_unbraked_kg', 'annual_km',
    'fuel_consumption_combined_l_100km', 'electricity_consumption_wh_per_km',
    'electric_range_km', 'tailpipe_co2_g_per_km', 'wltp_range_km',
    'fuel_tank_l', 'range_battery_km', 'range_petrol_km', 'range_total_km',
    # media / spotlight
    'image_url', 'spotlight_data', 'research_status',
    # pricing & costs (cents)
    'driveaway_price', 'driveaway_price_by_state',
    'servicing_5yr_estimate', 'tyre_replacement_estimate',
    'resale_value_5yr_estimate',
    'ctp_by_state', 'insurance_estimate_by_state', 'registration_by_state',
    'total_5yr_cost_of_ownership_by_state',
)

# Attribute on the record for each card field, per source. None = not
# available on that source (value stays null unless a fallback applies).
_FIELD_ATTRS = {
    'carreb': {
        'make': 'brand', 'fuel_consumption_combined_l_100km': 'fuel_consumption_per_100km',
        'electricity_consumption_wh_per_km': None,  # Vehicle stores kWh/100km
        'annual_km': 'annual_km_default',
        'spotlight_data': 'spotlight_data', 'research_status': 'research_status',
    },
    'gvg': {
        'fuel_type_raw': 'fuel_type_raw', 'research_status': None,
        'driveaway_price': 'driveaway_price_estimate',
    },
    'ai': {
        'research_status': None,
        'driveaway_price': 'driveaway_price_estimate',
    },
}

_GVG_MISSING = object()  # sentinel


def record_powertrain(card_or_record) -> str:
    """Normalised powertrain string used for applicability rules."""
    pt = getattr(card_or_record, 'powertrain_type', None)
    if pt is None and isinstance(card_or_record, dict):
        pt = card_or_record.get('powertrain_type')
    return re.sub(r'[^a-z0-9]+', '', str(pt or '').casefold())


def _fcai_broad_default(category: str) -> Optional[str]:
    """Broad vehicle class for an FCAI category, from the registry sheet."""
    if not category:
        return None
    row = FCAICategoryRegistry.objects.filter(
        carreb_db_label__iexact=category.strip()).first()
    if not row:
        # Registry labels sometimes carry price-band suffixes the card
        # category drops (e.g. "Small" vs "Small (under $40,000)").
        row = FCAICategoryRegistry.objects.filter(
            carreb_db_label__istartswith=category.strip()).first()
    if not row:
        return None
    return {
        'Passenger': 'Passenger Cars',
        'SUV': 'SUVs',
        'Light Commercial': 'Light Commercial',
    }.get(row.vehicle_class) or None


def _attr(record, field: str, source: str):
    """(value, provenance) for a field straight off the record."""
    attr = _FIELD_ATTRS.get(source, {}).get(field, field)
    if attr is None:
        return None, None
    value = getattr(record, attr, None)
    if value in (None, ''):
        return None, None
    # Empty containers also count as missing.
    if isinstance(value, (dict, list)) and not value:
        return None, None
    provenance = 'ai' if source == 'ai' else 'db'
    return value, provenance


def cached_spec_sheet(make, model, variant, year, powertrain: str = '') -> dict:
    """Cache-READ-ONLY variant for the request path: never calls Grok, so
    card building can never block a response on the AI. Returns {} when
    cold; a warmer (celery task / sweep / management command) fills the
    cache off-request."""
    sheet = cache.get(spec_sheet_cache_key(make, model, variant, year, powertrain))
    return sheet or {}


def _estimate_cache_key(kind: str, make, model, variant, year) -> str:
    return f"vc:est:{kind}:{make}|{model}|{variant}|{year}"


def _cached_estimate(kind: str, func, make, model, variant, year):
    key = _estimate_cache_key(kind, make, model, variant, year)
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    try:
        value = func(
            make=make or '', model=model or '',
            **({'variant': variant or ''} if kind == 'engine' else {}),
            year=year or 0)
    except Exception as exc:
        logger.warning("vehicle_card %s estimate failed for %s %s: %s",
                       kind, make, model, exc)
        value = None
    cache.set(key, value if value is not None else False, ESTIMATE_CACHE_TTL)
    return value


def _cached_estimate_read(kind: str, make, model, variant, year):
    """Cache-read-only counterpart of _cached_estimate for the request path."""
    cached = cache.get(_estimate_cache_key(kind, make, model, variant, year))
    return cached or None


def spec_sheet_cache_key(make, model, variant, year, powertrain: str = '') -> str:
    return (f"vc:est:specsheet:{make}|{model}|{variant}|{year}"
            f"|{powertrain or ''}")


def spec_sheet_for(make, model, variant, year, powertrain: str = '') -> dict:
    """Cached spec-sheet estimate for one car (30-day cache). Fetches from
    Grok on a cold cache; returns {} when the AI is unavailable. Pure
    values in/out so callers can run it off-thread without touching the ORM.
    """
    key = spec_sheet_cache_key(make, model, variant, year, powertrain)
    sheet = cache.get(key)
    if sheet is not None:
        return sheet or {}
    from apps.mygarage.ai_service import estimate_spec_sheet
    try:
        sheet = estimate_spec_sheet(make, model, variant, year, powertrain)
    except Exception as exc:
        logger.warning("vehicle_card spec-sheet estimate failed for "
                       "%s %s: %s", make, model, exc)
        sheet = {}
    cache.set(key, sheet or False, ESTIMATE_CACHE_TTL)
    return sheet or {}


SPEC_SHEET_FIELDS = ('transmission', 'doors', 'fuel_tank_l',
                     'tow_braked_kg', 'tow_unbraked_kg', 'test_cycle',
                     'variant')


def warm_estimates(make, model, variant, year, powertrain: str,
                   need_spec: bool, need_ancap: bool, need_engine: bool):
    """Populate the 30-day estimate caches for one car off-thread, so
    build_vehicle_card never fires a cold AI call inline. Pure values
    in/out — safe to run in a thread pool without touching the ORM.
    """
    if need_spec:
        spec_sheet_for(make, model, variant, year, powertrain)
    if need_ancap or need_engine:
        from apps.mygarage.ai_service import (
            estimate_ancap_rating,
            estimate_engine_displacement,
        )
        if need_ancap:
            _cached_estimate('ancap', estimate_ancap_rating,
                             make, model, variant, year)
        if need_engine:
            _cached_estimate('engine', estimate_engine_displacement,
                             make, model, variant, year)


def record_needs_warm(rec, source: str) -> tuple:
    """((job_args...), needs_any) for a GVG/AI record; (None, False) when
    nothing is missing or everything is already warm."""
    if source == 'carreb':
        return None, False
    make = getattr(rec, 'make', None) or getattr(rec, 'brand', '') or ''
    model = getattr(rec, 'model', '') or ''
    variant = getattr(rec, 'variant', '') or ''
    year = getattr(rec, 'year', None)
    powertrain = getattr(rec, 'powertrain_type', '') or ''
    need_spec = any(getattr(rec, f, None) in (None, '') for f in SPEC_SHEET_FIELDS)
    need_ancap = getattr(rec, 'ancap_safety_rating', None) is None
    need_engine = getattr(rec, 'engine_l', None) is None
    # Skip records whose caches are already warm.
    if need_spec and cached_spec_sheet(make, model, variant, year, powertrain):
        need_spec = False
    if need_ancap and _cached_estimate_read('ancap', make, model, variant, year):
        need_ancap = False
    if need_engine and _cached_estimate_read('engine', make, model, variant, year):
        need_engine = False
    job = (make, model, variant, year, powertrain,
           need_spec, need_ancap, need_engine)
    return job, (need_spec or need_ancap or need_engine)


def warm_cold_records(source: str, limit: int, offset: int = 0,
                      workers: int = 4) -> dict:
    """Warm estimate caches for up to ``limit`` cold records of a source,
    skipping rows that are already warm. Shared by the sweep task and the
    management command."""
    from concurrent.futures import ThreadPoolExecutor
    if source == 'ai':
        qs = AIVehicleEntry.objects.order_by('-search_count', '-created_at')
    else:
        qs = VehicleIdentity.objects.order_by('-year', 'make', 'model')
    total = qs.count()
    rows = list(qs[offset:offset + limit * 3])
    jobs = []
    already = 0
    for rec in rows:
        if len(jobs) >= limit:
            break
        job, needs = record_needs_warm(rec, source)
        if needs:
            jobs.append(job)
        else:
            already += 1
    if jobs:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda j: warm_estimates(*j), jobs))
    return {'warmed': len(jobs), 'already_warm': already, 'total': total,
            'next_offset': offset + len(jobs) + already,
            'remaining': max(0, total - offset - len(jobs) - already)}


def _ai_spec_fallbacks(record, source: str, make, model, variant, year):
    """Apply AI-estimated spec fields a GVG/AI record doesn't carry, from
    the 30-day estimate caches. READ-ONLY on the request path: this never
    calls Grok — warmers (celery tasks, nightly sweep, management command)
    populate the caches off-request, so card building stays instant.
    """
    out = {}
    if source not in ('gvg', 'ai'):
        return out

    missing = [f for f in SPEC_SHEET_FIELDS
               if getattr(record, f, None) in (None, '')]
    if missing:
        powertrain = getattr(record, 'powertrain_type', '') or ''
        sheet = cached_spec_sheet(make, model, variant, year, powertrain)
        for field in missing:
            if sheet.get(field) is not None:
                value = sheet[field]
                if field in ('tow_braked_kg', 'tow_unbraked_kg', 'doors'):
                    value = int(value)
                out[field] = (value, 'ai')

    if source == 'gvg':
        if getattr(record, 'ancap_safety_rating', None) is None:
            rating = _cached_estimate_read('ancap', make, model, variant, year)
            if rating:
                out['ancap_safety_rating'] = (rating, 'ai')
        if getattr(record, 'engine_l', None) is None:
            engine = _cached_estimate_read('engine', make, model, variant, year)
            if engine:
                out['engine_l'] = (engine, 'ai')
    return out


def nearest_catalogue_price(make: str, model: str, year: Optional[int],
                            exclude_id=None) -> Optional[int]:
    """Driveaway price (cents) of the nearest-year catalogue twin of this
    make+model — the 'defaults' tier for cars the sheet year doesn't cover
    (e.g. a 2025 Hilux when the catalogue only carries MY2026)."""
    if not make or not model:
        return None
    qs = Vehicle.objects.filter(brand__iexact=make.strip(),
                                model__iexact=model.strip())
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    best = None
    best_dist = None
    for v in qs.only('year', 'driveaway_price_by_state').iterator():
        prices = v.driveaway_price_by_state or {}
        price = prices.get('NSW') or next(iter(prices.values()), None)
        if not price:
            continue
        dist = abs((v.year or 0) - (year or 0))
        if best_dist is None or dist < best_dist:
            best, best_dist = price, dist
    return best


def _default_costs_by_state(record) -> dict:
    """Sheet-derived per-state cost dicts for records that lack them."""
    category = (getattr(record, 'fcai_category', None) or '').strip()
    if not category:
        return {}
    rows = {r.state: r for r in CategoryCostDefault.objects.filter(
        fcai_category__iexact=category)}
    out = {'ctp': {}, 'insurance': {}, 'registration': {}}
    for state, row in rows.items():
        if row.ctp_pa is not None:
            out['ctp'][state] = row.ctp_pa
        if row.comprehensive_pa is not None:
            out['insurance'][state] = row.comprehensive_pa
        if row.registration_pa is not None:
            out['registration'][state] = row.registration_pa
    return out


def _service_cost_fallback(record, field: str):
    """(value, provenance) from sheet defaults for servicing/tyres."""
    category = (getattr(record, 'fcai_category', None) or '').strip()
    if not category:
        return None, None
    row = CategoryCostDefault.objects.filter(
        fcai_category__iexact=category).first()
    if not row:
        return None, None
    if field == 'servicing_5yr_estimate' and row.servicing_5yr_estimate is not None:
        return row.servicing_5yr_estimate, 'default'
    if field == 'tyre_replacement_estimate' and row.tyre_replacement_estimate is not None:
        return row.tyre_replacement_estimate, 'default'
    return None, None


def build_vehicle_card(record, source: str, state: Optional[str] = None) -> dict:
    """Build the complete, provenance-tagged vehicle card for any record.

    ``record`` is a Vehicle (source='carreb'), VehicleIdentity ('gvg') or
    AIVehicleEntry ('ai'). ``state`` selects the default driveaway price.
    """
    make = getattr(record, 'brand', None) or getattr(record, 'make', '') or ''
    model = getattr(record, 'model', '') or ''
    year = getattr(record, 'year', None)
    variant = getattr(record, 'variant', '') or ''

    card: dict[str, Any] = {f: None for f in CARD_FIELDS}
    card['id'] = str(record.id)
    card['source'] = source
    card['name'] = f"{year or ''} {make} {model} {variant}".strip()
    card['field_sources'] = {}

    for field in CARD_FIELDS:
        if field in ('id', 'source', 'name', 'field_sources'):
            continue
        value, provenance = _attr(record, field, source)
        if value is not None:
            card[field] = value
            card['field_sources'][field] = provenance

    # Provenance truthfulness: an AI entry's cost fields are never produced
    # by the AI — fill_ai_entry_estimates sources them from the Data &
    # Assumptions sheets at entry creation. Only the pricing/spec fields on
    # the entry are actually Grok's.
    if source == 'ai':
        for field in ('ctp_by_state', 'insurance_estimate_by_state',
                      'registration_by_state', 'servicing_5yr_estimate',
                      'tyre_replacement_estimate',
                      'total_5yr_cost_of_ownership_by_state'):
            if field in card['field_sources']:
                card['field_sources'][field] = 'default'

    # Source-specific conversions.
    if source == 'carreb':
        kwh_per_100 = getattr(record, 'electricity_consumption_per_100km', None)
        if kwh_per_100 and card['electricity_consumption_wh_per_km'] is None:
            card['electricity_consumption_wh_per_km'] = round(kwh_per_100 * 1000 / 100, 1)
            card['field_sources']['electricity_consumption_wh_per_km'] = 'db'
        for f in ('fuel_tank_l', 'range_battery_km', 'range_petrol_km',
                  'range_total_km', 'doors'):
            v = getattr(record, f, None)
            if v not in (None, ''):
                card[f] = v
                card['field_sources'][f] = 'db'

    # AI-estimate missing spec fields (GVG + AI records).
    for field, (value, provenance) in _ai_spec_fallbacks(
            record, source, make, model, variant, year).items():
        if card[field] is None:
            card[field] = value
            card['field_sources'][field] = provenance

    # fcai_broad: deterministic registry lookup (category -> broad class).
    if card['fcai_broad'] is None and card['fcai_category']:
        broad = _fcai_broad_default(card['fcai_category'])
        if broad:
            card['fcai_broad'] = broad
            card['field_sources']['fcai_broad'] = 'default'

    # annual_km: catalogue default, else the category benchmark (sheets).
    if card['annual_km'] is None and card['fcai_category']:
        from apps.vehicles.models import CategoryAnnualKMBenchmark
        km = CategoryAnnualKMBenchmark.get_annual_km_for_category(
            card['fcai_category'])
        if km:
            card['annual_km'] = km
            card['field_sources']['annual_km'] = 'default'

    # Pure combustion cars factually have no battery/electric drivetrain:
    # report 0.0 instead of null so consumers never render "null". These are
    # structural truths, not estimates, so field_sources stays untouched.
    if (record_powertrain(card) in ('petrol', 'diesel')):
        for field in ('battery_kwh', 'electricity_consumption_wh_per_km',
                      'electric_range_km', 'wltp_range_km', 'range_battery_km'):
            if card[field] is None:
                card[field] = 0.0

    # Derived ranges: petrol range from tank ÷ consumption; total range adds
    # the electric leg for plug-ins (BEV total is the battery range).
    pt = record_powertrain(card)
    if card['range_petrol_km'] is None \
            and card['fuel_tank_l'] and card['fuel_consumption_combined_l_100km'] \
            and pt in ('petrol', 'diesel', 'hybrid', 'mildhybrid'):
        card['range_petrol_km'] = round(
            card['fuel_tank_l'] / card['fuel_consumption_combined_l_100km'] * 100)
        card['field_sources']['range_petrol_km'] = 'default'
    if card['range_total_km'] is None:
        legs = [v for v in (card['range_petrol_km'], card['range_battery_km'])
                if v]
        if pt == 'bev':
            legs = [v for v in (card['range_battery_km'], card['wltp_range_km'])
                    if v]
        if legs:
            card['range_total_km'] = sum(legs)
            card['field_sources']['range_total_km'] = 'default'

    # Driveaway price: state price → scalar estimate → nearest-year twin.
    if card['driveaway_price'] is None:
        by_state = card['driveaway_price_by_state'] or {}
        price = None
        if state:
            price = by_state.get(state)
        if price is None and by_state:
            price = by_state.get('NSW') or next(iter(by_state.values()), None)
        if price is None and source != 'carreb':
            price = nearest_catalogue_price(make, model, year,
                                            exclude_id=getattr(record, 'id', None))
            if price:
                card['field_sources']['driveaway_price'] = 'default'
        if price is not None:
            card['driveaway_price'] = price
        if 'driveaway_price' not in card['field_sources'] and price is not None:
            card['field_sources']['driveaway_price'] = \
                card['field_sources'].get('driveaway_price') or 'db'
    card['driveaway_price_display'] = (
        f"${card['driveaway_price'] // 100:,}" if card['driveaway_price'] else None)

    # Sheet-default cost fallbacks for records missing them.
    if not card['ctp_by_state'] or not card['insurance_estimate_by_state'] \
            or not card['registration_by_state']:
        defaults = _default_costs_by_state(record)
        for field, key in (('ctp_by_state', 'ctp'),
                           ('insurance_estimate_by_state', 'insurance'),
                           ('registration_by_state', 'registration')):
            if not card[field] and defaults.get(key):
                card[field] = defaults[key]
                card['field_sources'][field] = 'default'
    for field in ('servicing_5yr_estimate', 'tyre_replacement_estimate'):
        if card[field] is None:
            value, provenance = _service_cost_fallback(record, field)
            if value is not None:
                card[field] = value
                card['field_sources'][field] = provenance

    # 5yr ownership totals: record value → AI-entry filler output → leave.
    if not card['total_5yr_cost_of_ownership_by_state'] and source == 'ai':
        card['total_5yr_cost_of_ownership_by_state'] = \
            getattr(record, 'total_5yr_cost_of_ownership_by_state', None) or None
        if card['total_5yr_cost_of_ownership_by_state']:
            card['field_sources']['total_5yr_cost_of_ownership_by_state'] = 'default'

    # Image: record value → curated-on-disk / silhouette (never a random
    # web photo for non-catalogue cars).
    if not card['image_url']:
        from apps.vehicles.services.image_lookup import get_vehicle_image_url
        if source == 'carreb':
            card['image_url'] = get_vehicle_image_url(
                make, model, year=year, fcai_category=card['fcai_category'],
                body_style=card['body_style'], drive=card['drive'], delay=0.05)
        else:
            from apps.vehicles.services.image_lookup import get_used_vehicle_image_url
            card['image_url'] = get_used_vehicle_image_url(
                make, model, year=year, fcai_category=card['fcai_category'],
                body_style=card['body_style'], drive=card['drive'])
        card['field_sources']['image_url'] = card['field_sources'].get('image_url') or 'default'

    return card
