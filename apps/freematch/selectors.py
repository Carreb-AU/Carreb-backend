from typing import Optional
from django.db.models import QuerySet, Q

from apps.freematch.models import FreeMatchSession, FuelTypePreference, PrimaryUse
from apps.vehicles.models import Vehicle, PowertrainType

# Body style preferences per primary_use value.
PRIMARY_USE_BODY_STYLES: dict[str, list[str]] = {
    PrimaryUse.CITY_COMMUTER:  ["hatchback", "sedan"],
    PrimaryUse.FAMILY_CAR:     ["suv", "wagon"],
    PrimaryUse.MIXED_USE:      ["suv", "hatchback"],
    PrimaryUse.LONG_DISTANCE:  ["suv", "sedan"],
    PrimaryUse.WORK_VEHICLE:   ["ute", "van"],
}

def get_freematch_session(session_token: str) -> Optional[FreeMatchSession]:
    """
    Fetches a FreeMatchSession by its token. Returns None if not found.
    """
    try:
        return FreeMatchSession.objects.get(session_token=session_token)
    except FreeMatchSession.DoesNotExist:
        return None

def get_freematch_candidates(session: FreeMatchSession) -> QuerySet[Vehicle]:
    """
    Returns a queryset of candidate vehicles based on the session fields.
    Excludes FCEV vehicles as they have no CORE Rating at launch, and
    suppressed (held) listings.
    """
    qs = Vehicle.objects.exclude(powertrain_type=PowertrainType.FCEV).filter(is_suppressed=False)
    
    # Fuel Preference
    fuel_pref = session.fuel_type_preference
    if fuel_pref and fuel_pref != FuelTypePreference.NO_PREFERENCE:
        qs = qs.filter(powertrain_type=fuel_pref)
        
    # Style / Shape
    if session.style_preference:
        qs = qs.filter(body_style__icontains=session.style_preference)
    elif session.primary_use:
        body_styles = PRIMARY_USE_BODY_STYLES.get(session.primary_use, [])
        if body_styles:
            q = Q()
            for style in body_styles:
                q |= Q(body_style__icontains=style)
            qs = qs.filter(q)
            
    # Seating
    if session.seating_preference:
        qs = qs.filter(num_seats__gte=session.seating_preference)
        
    # ANCAP Safety
    if session.ancap_5_star_only:
        qs = qs.filter(ancap_safety_rating__gte=5)
        
    # Budget Min/Max
    # driveaway_price_by_state is a JSON field. We filter using the json lookup on the state.
    state = session.state or "NSW"
    if session.budget_min is not None:
        qs = qs.filter(**{f"driveaway_price_by_state__{state}__gte": session.budget_min * 100})
    if session.budget_max is not None:
        qs = qs.filter(**{f"driveaway_price_by_state__{state}__lte": session.budget_max * 100})
            
    return qs

def get_freematch_candidates_base() -> QuerySet[Vehicle]:
    """
    Returns base candidate queryset without any filters except FCEV
    and suppressed-listing exclusions.
    """
    return Vehicle.objects.exclude(powertrain_type=PowertrainType.FCEV).filter(is_suppressed=False)

def get_freematch_candidates_relaxed(session: FreeMatchSession) -> QuerySet[Vehicle]:
    """
    Attempt-2 relaxation, downward only: drops the budget FLOOR (a car
    cheaper than budget_min is still a fine suggestion) but keeps the
    budget CEILING — never suggest cars above budget_max. ANCAP and
    seating floors relax only when nothing matches with them. Keeps the
    fundamental requirements: body style and fuel type.
    """
    qs = Vehicle.objects.exclude(powertrain_type=PowertrainType.FCEV).filter(is_suppressed=False)

    # Fuel Preference
    fuel_pref = session.fuel_type_preference
    if fuel_pref and fuel_pref != FuelTypePreference.NO_PREFERENCE:
        qs = qs.filter(powertrain_type=fuel_pref)

    # Style / Shape
    if session.style_preference:
        qs = qs.filter(body_style__icontains=session.style_preference)
    elif session.primary_use:
        body_styles = PRIMARY_USE_BODY_STYLES.get(session.primary_use, [])
        if body_styles:
            q = Q()
            for style in body_styles:
                q |= Q(body_style__icontains=style)
            qs = qs.filter(q)

    # Seating (only enforce if there is at least one vehicle that meets it)
    if session.seating_preference:
        if qs.filter(num_seats__gte=session.seating_preference).exists():
            qs = qs.filter(num_seats__gte=session.seating_preference)

    # Budget ceiling is kept: budget_max still applies, only the floor drops.
    state = session.state or "NSW"
    if session.budget_max is not None:
        qs = qs.filter(**{f"driveaway_price_by_state__{state}__lte": session.budget_max * 100})

    return qs

def get_freematch_candidates_fuel_only(fuel_pref: Optional[str]) -> QuerySet[Vehicle]:
    """
    Returns candidate queryset with only the fuel filter applied.
    """
    qs = Vehicle.objects.exclude(powertrain_type=PowertrainType.FCEV).filter(is_suppressed=False)
    if fuel_pref and fuel_pref != FuelTypePreference.NO_PREFERENCE:
        qs = qs.filter(powertrain_type=fuel_pref)
    return qs
