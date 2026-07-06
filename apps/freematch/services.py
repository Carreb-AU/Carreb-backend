"""
Free Match Wizard — service layer.

All vehicle scoring is delegated to the CORE Rating Engine
(apps.vehicles.services.rating_engine).  No cost or rating
figures are computed here — this module only filters candidates
and picks the highest-scoring one.
State mutations and complex business logic live here.
"""

import logging
from typing import Optional

from django.db import transaction

from apps.freematch.models import FreeMatchSession
from apps.freematch.selectors import (
    get_freematch_candidates,
    get_freematch_candidates_base,
    get_freematch_candidates_fuel_only,
)
from apps.vehicles.models import Vehicle
from apps.vehicles.services.rating_engine import calculate_core_rating
from apps.mygarage.models import GarageVehicle, GarageVehicleSource

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

WIZARD_PRIORITY_SLIDER = 3
WIZARD_CORE_MODE = "pure_cost"
WIZARD_DEFAULT_STATE = "NSW"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _score_and_pick_best(candidates) -> Optional[Vehicle]:
    """
    Score each candidate with the CORE Rating Engine and return
    the single highest-scoring vehicle.
    """
    if not candidates:
        return None

    best_vehicle = None
    best_score = -1.0
    category_metrics_cache = {}

    for vehicle in candidates:
        try:
            result = calculate_core_rating(
                vehicle=vehicle,
                state=WIZARD_DEFAULT_STATE,
                priority_slider=WIZARD_PRIORITY_SLIDER,
                core_mode=WIZARD_CORE_MODE,
                user_inputs={},
                current_vehicle_annual_cost=None,
                category_metrics_cache=category_metrics_cache
            )
            rating = result.get("core_rating")
            if rating is None:
                continue
            if rating > best_score:
                best_score = rating
                best_vehicle = vehicle
        except Exception:
            logger.exception("CORE Rating Engine error for vehicle %s — skipping", vehicle.id)

    return best_vehicle


# ── Match Logic ──────────────────────────────────────────────────────────────

def match_vehicle_for_wizard(session: FreeMatchSession) -> Optional[Vehicle]:
    """
    Run the Free Match Wizard matching algorithm.
    """
    fuel_pref = session.fuel_type_preference
    primary_use = session.primary_use

    # ── Attempt 1: fuel + body style ─────────────────────────────────────
    candidates = list(get_freematch_candidates(fuel_pref, primary_use))

    if candidates:
        vehicle = _score_and_pick_best(candidates)
        if vehicle:
            return vehicle

    # ── Attempt 2: fuel only (relax body style) ──────────────────────────
    logger.info(
        "Free match wizard: no results with body style filter — relaxing (session %s)",
        session.session_token[:8],
    )
    candidates = list(get_freematch_candidates_fuel_only(fuel_pref))

    if candidates:
        vehicle = _score_and_pick_best(candidates)
        if vehicle:
            return vehicle

    # ── Attempt 3: no filters (relax fuel type too) ──────────────────────
    logger.info(
        "Free match wizard: no results with fuel filter — relaxing all (session %s)",
        session.session_token[:8],
    )
    candidates = list(get_freematch_candidates_base())

    if not candidates:
        raise RuntimeError("Vehicle catalogue is empty — cannot produce a match.")

    vehicle = _score_and_pick_best(candidates)
    if not vehicle:
        raise RuntimeError("CORE Rating Engine returned no scorable vehicle.")

    return vehicle


# ── Response Builders ────────────────────────────────────────────────────────

def build_match_response(vehicle: Vehicle, session: FreeMatchSession) -> dict:
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
            "core_rating": engine_data.get("core_rating"),
            "band_name": engine_data.get("band_name"),
            "annual_running_cost_estimate": annual_cost_cents,
            "annual_running_cost_display": _format_cents(annual_cost_cents),
            "co2_g_per_km": co2,
            "is_estimate": True,
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
    from django.utils import timezone

    cv = getattr(user, "current_vehicle", None)
    state = (cv.state if cv and cv.state else None) or WIZARD_DEFAULT_STATE

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

def _format_cents(cents: int) -> str:
    if cents is None:
        return "$0"
    dollars = cents / 100
    sign = "-" if dollars < 0 else ""
    return f"{sign}${abs(dollars):,.0f}"

# ── State Mutations ──────────────────────────────────────────────────────────

def create_freematch_session() -> FreeMatchSession:
    return FreeMatchSession.objects.create()

def update_freematch_step_1(session: FreeMatchSession, data: dict):
    session.has_current_vehicle = data["has_current_vehicle"]
    session.save(update_fields=["has_current_vehicle"])

def update_freematch_step_2(session: FreeMatchSession, data: dict):
    session.current_vehicle_make = data["current_vehicle_make"]
    session.current_vehicle_model = data["current_vehicle_model"]
    session.current_vehicle_year = data["current_vehicle_year"]
    session.save(
        update_fields=[
            "current_vehicle_make",
            "current_vehicle_model",
            "current_vehicle_year",
        ]
    )

def update_freematch_step_3(session: FreeMatchSession, data: dict):
    session.fuel_type_preference = data["fuel_type_preference"]
    session.annual_km = data["annual_km"]
    session.primary_use = data["primary_use"]
    session.save(
        update_fields=["fuel_type_preference", "annual_km", "primary_use"]
    )

def set_matched_vehicle(session: FreeMatchSession, vehicle: Vehicle):
    session.matched_vehicle = vehicle
    session.save(update_fields=["matched_vehicle"])

@transaction.atomic
def convert_session_to_garage(session: FreeMatchSession, user) -> GarageVehicle:
    garage_vehicle = GarageVehicle.objects.create(
        user=user,
        vehicle_catalogue=session.matched_vehicle,
        source=GarageVehicleSource.FREE_MATCH_WIZARD,
    )
    session.converted_user = user
    session.save(update_fields=["converted_user"])
    return garage_vehicle

def discard_freematch_session(session: FreeMatchSession):
    session.delete()
