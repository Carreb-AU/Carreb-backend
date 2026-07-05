"""
Free Match Wizard — service layer.

All vehicle scoring is delegated to the CORE Rating Engine
(apps.vehicles.services.rating_engine).  No cost or rating
figures are computed here — this module only filters candidates
and picks the highest-scoring one.
"""

import logging
from typing import Optional

from apps.freematch.models import FreeMatchSession, FuelTypePreference, PrimaryUse
from apps.vehicles.models import Vehicle, PowertrainType
from apps.vehicles.services.rating_engine import calculate_core_rating

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Balanced priority + Pure Cost — wizard always uses these defaults.
WIZARD_PRIORITY_SLIDER = 3
WIZARD_CORE_MODE = "pure_cost"

# National average state used for anonymous matching.
WIZARD_DEFAULT_STATE = "NSW"

# Body style preferences per primary_use value.
# Keys are PrimaryUse enum values; values are lists of body_style strings
# (case-insensitive match performed at query time).
PRIMARY_USE_BODY_STYLES: dict[str, list[str]] = {
    PrimaryUse.CITY_COMMUTER:  ["hatchback", "sedan"],
    PrimaryUse.FAMILY_CAR:     ["suv", "wagon"],
    PrimaryUse.MIXED_USE:      ["suv", "hatchback"],
    PrimaryUse.LONG_DISTANCE:  ["suv", "sedan"],
    PrimaryUse.WORK_VEHICLE:   ["ute", "van"],
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _base_queryset():
    """
    Starting point for all Free Match queries.
    Excludes FCEV (no CORE Rating at launch).
    Only new vehicles exist in the catalogue so no used-vehicle filter
    is needed — the catalogue is new-only by platform rule.
    """
    return Vehicle.objects.exclude(powertrain_type=PowertrainType.FCEV)


def _apply_fuel_filter(qs, fuel_pref: Optional[str]):
    """Apply powertrain filter if a specific fuel preference was chosen."""
    if fuel_pref and fuel_pref != FuelTypePreference.NO_PREFERENCE:
        # Map wizard fuel enum to Vehicle.powertrain_type choices.
        # They share the same string values so this is a direct match.
        qs = qs.filter(powertrain_type=fuel_pref)
    return qs


def _apply_body_style_filter(qs, primary_use: Optional[str]):
    """Apply body style filter derived from primary_use preference."""
    if not primary_use:
        return qs
    body_styles = PRIMARY_USE_BODY_STYLES.get(primary_use, [])
    if not body_styles:
        return qs
    from django.db.models import Q
    q = Q()
    for style in body_styles:
        q |= Q(body_style__iexact=style)
    return qs.filter(q)


def _score_and_pick_best(candidates) -> Optional[Vehicle]:
    """
    Score each candidate with the CORE Rating Engine and return
    the single highest-scoring vehicle.

    Returns None only when candidates is empty (should not happen
    after progressive relaxation, but handled defensively).
    """
    if not candidates:
        return None

    best_vehicle = None
    best_score = -1.0

    for vehicle in candidates:
        try:
            result = calculate_core_rating(
                vehicle=vehicle,
                state=WIZARD_DEFAULT_STATE,
                priority_slider=WIZARD_PRIORITY_SLIDER,
                core_mode=WIZARD_CORE_MODE,
                user_inputs={},
                current_vehicle_annual_cost=None,
            )
            rating = result.get("core_rating")
            if rating is None:
                # FCEV or engine gap — should be excluded already but guard anyway
                continue
            if rating > best_score:
                best_score = rating
                best_vehicle = vehicle
        except Exception:
            logger.exception("CORE Rating Engine error for vehicle %s — skipping", vehicle.id)

    return best_vehicle


# ── Public API ───────────────────────────────────────────────────────────────

def match_vehicle_for_wizard(session: FreeMatchSession) -> Optional[Vehicle]:
    """
    Run the Free Match Wizard matching algorithm.

    Match logic (applied in strict order):
    1. Exclude FCEV vehicles.
    2. Filter by fuel_type_preference (skip if no_preference).
    3. Filter by body style mapped from primary_use.
    4. Score with CORE Rating Engine (Balanced / Pure Cost / NSW).
    5. Return single highest-scoring vehicle.
    6. Progressive relaxation:
       a. If no results → remove body style filter → retry.
       b. If still no results → remove fuel type filter too → retry.

    Raises RuntimeError if the catalogue is completely empty
    (treated as a 503 upstream).
    """
    fuel_pref = session.fuel_type_preference
    primary_use = session.primary_use

    # ── Attempt 1: fuel + body style ─────────────────────────────────────
    qs = _base_queryset()
    qs = _apply_fuel_filter(qs, fuel_pref)
    qs = _apply_body_style_filter(qs, primary_use)
    candidates = list(qs)

    if candidates:
        vehicle = _score_and_pick_best(candidates)
        if vehicle:
            return vehicle

    # ── Attempt 2: fuel only (relax body style) ──────────────────────────
    logger.info(
        "Free match wizard: no results with body style filter — relaxing (session %s)",
        session.session_token[:8],
    )
    qs = _base_queryset()
    qs = _apply_fuel_filter(qs, fuel_pref)
    candidates = list(qs)

    if candidates:
        vehicle = _score_and_pick_best(candidates)
        if vehicle:
            return vehicle

    # ── Attempt 3: no filters (relax fuel type too) ──────────────────────
    logger.info(
        "Free match wizard: no results with fuel filter — relaxing all (session %s)",
        session.session_token[:8],
    )
    candidates = list(_base_queryset())

    if not candidates:
        raise RuntimeError("Vehicle catalogue is empty — cannot produce a match.")

    vehicle = _score_and_pick_best(candidates)
    if not vehicle:
        raise RuntimeError("CORE Rating Engine returned no scorable vehicle.")

    return vehicle


def build_match_response(vehicle: Vehicle, session: FreeMatchSession) -> dict:
    """
    Build the partial match response shown to anonymous visitors.

    Visible fields: core_rating, band_name, annual_running_cost, co2.
    Gated fields: resale_value_5yr_estimate, est_cost_difference,
                  driveaway_price_estimate — returned as locked: true, value: null.

    All monetary figures in cents + formatted_display strings.
    """
    from django.utils import timezone

    engine_data = calculate_core_rating(
        vehicle=vehicle,
        state=WIZARD_DEFAULT_STATE,
        priority_slider=WIZARD_PRIORITY_SLIDER,
        core_mode=WIZARD_CORE_MODE,
        user_inputs={},
        current_vehicle_annual_cost=None,
    )

    annual_cost_cents = engine_data.get("total_annual_cost") or 0
    co2 = vehicle.tailpipe_co2_g_per_km

    return {
        "vehicle": {
            "id": str(vehicle.id),
            "make": vehicle.brand,
            "model": vehicle.model,
            "year": vehicle.year,
            "variant": vehicle.variant,
            "powertrain_type": vehicle.powertrain_type,
            # ── Visible to everyone ──────────────────────────────────────
            "core_rating": engine_data.get("core_rating"),
            "band_name": engine_data.get("band_name"),
            "annual_running_cost_estimate": annual_cost_cents,
            "annual_running_cost_display": _format_cents(annual_cost_cents),
            "co2_g_per_km": co2,
            "is_estimate": True,
            # ── Gated behind sign-up ─────────────────────────────────────
            "resale_value_5yr_estimate": {"locked": True, "value": None},
            "est_cost_difference": {"locked": True, "value": None},
            "driveaway_price_estimate": {"locked": True, "value": None},
        },
        "session_token": session.session_token,
        "meta": {
            "calculated_at": timezone.now().isoformat(),
            "is_estimate": True,
            "disclaimer": (
                "All figures are estimates only. Actual costs will vary based on "
                "individual driving habits, insurer quotes, dealer pricing, and "
                "personal circumstances."
            ),
        },
    }


def build_unlocked_response(vehicle: Vehicle, user, garage_vehicle) -> dict:
    """
    Full vehicle detail shown after a visitor signs up and saves the result.
    Calls the CORE Rating Engine with the user's state and default settings,
    then returns the same shape as MyGarage vehicle detail.
    """
    from django.utils import timezone
    from apps.mygarage.models import UserPriorityState, CoreMode

    # Determine user's state from their priority / current vehicle if available.
    cv = getattr(user, "current_vehicle", None)
    state = (cv.state if cv and cv.state else None) or WIZARD_DEFAULT_STATE

    # Use user's priority state if set, otherwise wizard defaults.
    try:
        priority_state = user.priority_state
        priority_slider = priority_state.priority_slider_position
        core_mode = priority_state.active_core_mode
    except Exception:
        priority_slider = WIZARD_PRIORITY_SLIDER
        core_mode = WIZARD_CORE_MODE

    engine_data = calculate_core_rating(
        vehicle=vehicle,
        state=state,
        priority_slider=priority_slider,
        core_mode=core_mode,
        user_inputs={},
        current_vehicle_annual_cost=None,
    )

    annual_cost_cents = engine_data.get("total_annual_cost") or 0
    driveaway_cents = vehicle.driveaway_price_by_state.get(state) or 0
    resale_cents = vehicle.resale_value_5yr_estimate or 0
    est_diff_cents = engine_data.get("est_cost_difference") or 0

    return {
        "garage_vehicle_id": str(garage_vehicle.id),
        "vehicle": {
            "id": str(vehicle.id),
            "make": vehicle.brand,
            "model": vehicle.model,
            "year": vehicle.year,
            "variant": vehicle.variant,
            "powertrain_type": vehicle.powertrain_type,
            "core_rating": engine_data.get("core_rating"),
            "band_name": engine_data.get("band_name"),
            "band_slug": engine_data.get("band_slug"),
            "annual_running_cost_estimate": annual_cost_cents,
            "annual_running_cost_display": _format_cents(annual_cost_cents),
            "co2_g_per_km": vehicle.tailpipe_co2_g_per_km,
            "is_estimate": True,
            # ── Unlocked ─────────────────────────────────────────────────
            "resale_value_5yr_estimate": resale_cents,
            "resale_value_5yr_display": _format_cents(resale_cents),
            "est_cost_difference": est_diff_cents,
            "est_cost_difference_display": _format_cents(est_diff_cents),
            "driveaway_price_estimate": driveaway_cents,
            "driveaway_price_display": _format_cents(driveaway_cents),
        },
        "meta": {
            "calculated_at": timezone.now().isoformat(),
            "is_estimate": True,
            "disclaimer": (
                "All figures are estimates only. Actual costs will vary based on "
                "individual driving habits, insurer quotes, dealer pricing, and "
                "personal circumstances."
            ),
        },
    }


# ── Formatting helpers ────────────────────────────────────────────────────────

def _format_cents(cents: int) -> str:
    """
    Convert an integer cents value to an AUD display string.
    e.g. 466000 → "$4,660"
    Handles negative values (savings) with a leading minus sign.
    """
    if cents is None:
        return "$0"
    dollars = cents / 100
    sign = "-" if dollars < 0 else ""
    return f"{sign}${abs(dollars):,.0f}"
