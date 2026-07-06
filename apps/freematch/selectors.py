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

def get_freematch_candidates(fuel_pref: Optional[str], primary_use: Optional[str]) -> QuerySet[Vehicle]:
    """
    Returns a queryset of candidate vehicles based on the fuel preference
    and primary use. Excludes FCEV vehicles as they have no CORE Rating at launch.
    """
    qs = Vehicle.objects.exclude(powertrain_type=PowertrainType.FCEV)
    
    if fuel_pref and fuel_pref != FuelTypePreference.NO_PREFERENCE:
        qs = qs.filter(powertrain_type=fuel_pref)
        
    if primary_use:
        body_styles = PRIMARY_USE_BODY_STYLES.get(primary_use, [])
        if body_styles:
            q = Q()
            for style in body_styles:
                q |= Q(body_style__iexact=style)
            qs = qs.filter(q)
            
    return qs

def get_freematch_candidates_base() -> QuerySet[Vehicle]:
    """
    Returns base candidate queryset without any filters except FCEV exclusion.
    """
    return Vehicle.objects.exclude(powertrain_type=PowertrainType.FCEV)

def get_freematch_candidates_fuel_only(fuel_pref: Optional[str]) -> QuerySet[Vehicle]:
    """
    Returns candidate queryset with only the fuel filter applied.
    """
    qs = Vehicle.objects.exclude(powertrain_type=PowertrainType.FCEV)
    if fuel_pref and fuel_pref != FuelTypePreference.NO_PREFERENCE:
        qs = qs.filter(powertrain_type=fuel_pref)
    return qs
