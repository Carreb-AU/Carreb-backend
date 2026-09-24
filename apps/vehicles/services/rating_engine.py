from typing import Dict, Any, Optional
from decimal import Decimal
import math
import statistics
from django.utils import timezone
from apps.vehicles.models import Vehicle, PowertrainType
from apps.vehicles.selectors import get_vehicles_by_fcai_category

# Trademarked Band Names
BAND_NAMES = {
    (4.5, 5.0): "Net Zero Ninja™",
    (3.5, 4.4): "Smart Move™",
    (2.5, 3.4): "Steady Cruiser™",
    (1.5, 2.4): "The Detour™",
    (1.0, 1.4): "Captain Carbon™",
}

def get_band_name(rating) -> str:
    if rating is None:
        return ""
    rating = float(rating)
    for (min_val, max_val), name in BAND_NAMES.items():
        if min_val <= rating <= max_val:
            return name
    return "Captain Carbon™" # Fallback

def get_band_slug(rating) -> str:
    if rating is None:
        return ""
    rating = float(rating)
    if rating >= 4.5: return "net-zero-ninja"
    if rating >= 3.5: return "smart-move"
    if rating >= 2.5: return "steady-cruiser"
    if rating >= 1.5: return "the-detour"
    return "captain-carbon"


# Spec §4 fixed-band mode letters. Used to read pre-computed batch scores from
# Vehicle.mode_data_by_state.
CORE_MODE_TO_KEY = {
    'pure_cost': 'B',
    'cool_choice': 'E',
    'true_value': 'C',
    'full_picture': 'F',
}

# Spec §4 mode weights. Pure Cost and COOL Choice are cost-weighted;
# True Value is emissions-weighted; Full Picture is balanced.
CORE_MODE_WEIGHTS = {
    'pure_cost': (0.80, 0.20),
    'cool_choice': (0.80, 0.20),
    'true_value': (0.20, 0.80),
    'full_picture': (0.50, 0.50),
}


def _get_stored_mode_data(vehicle, state: str, core_mode: str) -> Optional[Dict[str, Any]]:
    """Return pre-computed workbook data for a state/mode, or None.

    Values are stored as provided by the v6.3.4 workbook:
      * money fields are dollars
      * scores are 0..1
      * stars is 1..5
      * annual_co2_kg is kg/year
    """
    mode_data = getattr(vehicle, 'mode_data_by_state', None) or {}
    if not mode_data or not isinstance(mode_data, dict):
        return None

    clean_state = (state or 'NSW').upper()
    state_data = mode_data.get(clean_state)
    if not isinstance(state_data, dict):
        return None

    key = CORE_MODE_TO_KEY.get(core_mode, 'B')
    md = state_data.get(key)

    if not md or not isinstance(md, dict):
        # Tolerate alternate spellings of the mode key in the source sheet.
        for alt in (core_mode.upper(), core_mode.replace('_', ' ').upper()):
            if state_data.get(alt):
                md = state_data[alt]
                break
        if not md or not isinstance(md, dict):
            return None

    required = ('mode_coo_pa', 'stars')
    if any(md.get(k) is None for k in required):
        return None

    return {
        'mode_coo_pa': float(md['mode_coo_pa']),
        'annual_co2_kg': float(md.get('annual_co2_kg') or 0),
        'stars': int(round(float(md['stars']))),
        'price_score': float(md.get('price_score') or 0),
        'emissions_score': float(md.get('emissions_score') or 0),
        'core_score': float(md.get('core_score') or 0),
        'finance_cost_pa': md.get('finance_cost_pa'),
        'resale_credit_pa': md.get('resale_credit_pa'),
    }


def _co2_star_cap(powertrain: str, tailpipe_co2: Optional[float]) -> Optional[float]:
    """Absolute CO2 star-cap on the 1-5 scale (Spec §4/E2). BEV/FCEV are never capped."""
    if powertrain in (PowertrainType.BEV, PowertrainType.FCEV):
        return None
    co2 = tailpipe_co2 or 0
    if co2 >= 250:
        return 2.4
    if co2 >= 200:
        return 3.4
    if co2 >= 150:
        return 4.4
    return None


def _apply_co2_cap(blended_score: float, powertrain: str, tailpipe_co2: Optional[float]) -> tuple[float, bool, Optional[float]]:
    """Return (capped_score, cap_applied, cap_threshold)."""
    cap = _co2_star_cap(powertrain, tailpipe_co2)
    if cap is not None and blended_score > cap:
        return cap, True, cap
    return blended_score, False, None


def _co2_star_cap_stars(powertrain: str, tailpipe_co2: Optional[float]) -> Optional[int]:
    """Absolute CO2 cap expressed as a whole-star ceiling."""
    if powertrain in (PowertrainType.BEV, PowertrainType.FCEV):
        return None
    co2 = tailpipe_co2 or 0
    if co2 >= 250:
        return 2
    if co2 >= 200:
        return 3
    if co2 >= 150:
        return 4
    return None


def _apply_star_co2_cap(stars: int, powertrain: str, tailpipe_co2: Optional[float]) -> tuple[int, bool, Optional[int]]:
    """Return (capped_stars, cap_applied, cap_threshold)."""
    cap = _co2_star_cap_stars(powertrain, tailpipe_co2)
    if cap is not None and stars > cap:
        return cap, True, cap
    return stars, False, None


def calculate_monthly_repayment(principal: float, annual_rate: float, months: int) -> float:
    if annual_rate == 0:
        return principal / months
    monthly_rate = (annual_rate / 100.0) / 12
    repayment = principal * (monthly_rate * math.pow(1 + monthly_rate, months)) / (math.pow(1 + monthly_rate, months) - 1)
    return repayment


def _normalize_driveaway_for_loan(driveaway) -> float:
    """Return driveaway price in dollars for the loan calculator.

    driveaway_price_by_state is usually stored as whole cents. Older imports may
    have stored dollars as floats; convert those to cents first.
    """
    if not driveaway:
        return 0.0

    # Float means dollars in the old import; convert to cents.
    if isinstance(driveaway, float):
        driveaway = int(round(driveaway * 100))

    # $10,000 = 1,000,000 cents. Anything larger than that is almost certainly cents.
    if driveaway > 1_000_000:
        return driveaway / 100.0
    return float(driveaway)


def _get_state_value(json_field: dict, state: str, default_val=0) -> int:
    if not json_field or not isinstance(json_field, dict):
        return default_val
    val = json_field.get(state)
    if val is None and state:
        val = json_field.get(state.upper())
    if val is None:
        val = json_field.get('NSW')
    if val is None and json_field:
        val = next(iter(json_field.values()), default_val)
    return val if val is not None else default_val


def _to_cents(value) -> int:
    """Convert a stored money value to whole cents.

    The Carreb ETL historically stored some monetary fields as dollar floats
    while other importers stored them as cents. We normalise at read time:
      - floats (with decimals) -> dollars -> cents
      - ints are treated as already-cents, except for the two 5-year estimates
        which the ETL stored as int dollars.
    """
    if value is None or value == '':
        return 0
    if isinstance(value, bool):
        return 0
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        return int(round(value * 100))
    if isinstance(value, int):
        return value
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return 0


def _get_state_cents(json_field: dict, state: str, default_val=0) -> int:
    return _to_cents(_get_state_value(json_field, state, default_val))


def _estimate_to_cents(value, field_name: str) -> int:
    """Handle the 5-year estimate fields which may be stored as int dollars."""
    if value is None or value == '':
        return 0
    if isinstance(value, float):
        return int(round(value * 100))
    if isinstance(value, int):
        # The old Carreb ETL stored these as int dollars; anything under $10k
        # for 5 years of servicing/tyres is almost certainly dollars.
        if field_name in ('servicing_5yr_estimate', 'tyre_replacement_estimate') and 0 < value < 1_000_000:
            return value * 100
        return value
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return 0


def calculate_vehicle_cost_breakdown(
    vehicle: Vehicle,
    state: str,
    core_mode: str,
    user_inputs: Dict[str, Any]
) -> Dict[str, Any]:

    state = (state or 'NSW').upper()
    annual_km = user_inputs.get('annual_km', vehicle.annual_km_default or 13300)

    driveaway = user_inputs.get('driveaway_override')
    if not driveaway:
        driveaway = _get_state_cents(getattr(vehicle, 'driveaway_price_by_state', None), state, 0)

    stored_mode = _get_stored_mode_data(vehicle, state, core_mode)

    # 1. Fuel / Energy — stored as either annual cents or annual dollars.
    fuel_annual = _get_state_cents(getattr(vehicle, 'fuel_cost_by_state', None), state)
    elec_annual = _get_state_cents(getattr(vehicle, 'electricity_cost_by_state', None), state)
    fuel_or_energy_annual = fuel_annual + elec_annual

    # 2. Insurance / registration / CTP
    insurance = _get_state_cents(getattr(vehicle, 'insurance_estimate_by_state', None), state)
    ctp = _get_state_cents(getattr(vehicle, 'ctp_by_state', None), state)
    rego = _get_state_cents(getattr(vehicle, 'registration_by_state', None), state)
    ev_levy = _get_state_cents(getattr(vehicle, 'ev_levy_by_state', None), state)

    # 3. Servicing and tyres — stored as 5-year totals, either cents or dollars.
    servicing_annual = _estimate_to_cents(getattr(vehicle, 'servicing_5yr_estimate', 0), 'servicing_5yr_estimate') // 5
    tyres_annual = _estimate_to_cents(getattr(vehicle, 'tyre_replacement_estimate', 0), 'tyre_replacement_estimate') // 5

    # 4. If we have no component data, fall back to a canonical 5-year aggregate.
    if not any([fuel_or_energy_annual, insurance, ctp, rego, servicing_annual, tyres_annual, ev_levy]):
        total_5yr = _get_state_cents(getattr(vehicle, 'total_5yr_cost_of_ownership_by_state', None), state)
        if total_5yr:
            annual_aggregate = total_5yr // 5
            non_fuel_annual = max(0, annual_aggregate - fuel_or_energy_annual)
            servicing_annual = non_fuel_annual

    # 5. Depreciation / other fixed ownership costs. The workbook stores a
    # canonical base_coo_pa that is larger than the sum of running-cost components.
    base_coo = _get_state_cents(getattr(vehicle, 'base_coo_by_state', None), state)
    components_sum = _get_state_cents(getattr(vehicle, 'components_sum_by_state', None), state)
    other_annual = 0
    if base_coo and components_sum:
        other_annual = max(0, int(base_coo) - int(components_sum))

    # 6. Mode-specific finance / resale. Prefer pre-computed workbook values.
    finance_annual = 0
    if core_mode in ['cool_choice', 'full_picture']:
        if stored_mode and stored_mode.get('finance_cost_pa') is not None:
            finance_annual = int(round(float(stored_mode['finance_cost_pa']) * 100))
        else:
            driveaway_dollars = _normalize_driveaway_for_loan(driveaway)
            loan_amount = user_inputs.get('loan_amount', driveaway_dollars * 0.8)  # 20% deposit
            interest_rate = user_inputs.get('interest_rate', 7.5)
            loan_term_months = user_inputs.get('loan_term_months', 60)
            monthly = calculate_monthly_repayment(loan_amount, interest_rate, loan_term_months)
            finance_annual = int(monthly * 12 * 100)  # dollars/month -> cents/year

    resale_annual = 0
    if core_mode in ['true_value', 'full_picture']:
        if stored_mode and stored_mode.get('resale_credit_pa') is not None:
            resale_annual = int(round(float(stored_mode['resale_credit_pa']) * 100))
        else:
            resale_annual = int((getattr(vehicle, 'resale_value_5yr_estimate', 0) or 0) / 5)

    base_total = fuel_or_energy_annual + insurance + ctp + rego + servicing_annual + tyres_annual + ev_levy + other_annual
    total = base_total
    if core_mode in ['cool_choice', 'full_picture']:
        total += finance_annual
    if core_mode in ['true_value', 'full_picture']:
        total -= resale_annual

    return {
        "fuel_or_energy_annual": fuel_or_energy_annual,
        "insurance_annual": insurance,
        "ctp_annual": ctp,
        "registration_annual": rego,
        "servicing_annual": servicing_annual,
        "tyres_annual": tyres_annual,
        "ev_levy_annual": ev_levy,
        "other_annual": other_annual,
        "finance_annual": finance_annual if core_mode in ['cool_choice', 'full_picture'] else 0,
        "resale_credit_annual": resale_annual if core_mode in ['true_value', 'full_picture'] else 0,
        "total_annual": total,
        "driveaway_price": driveaway
    }


def calculate_core_rating(
    vehicle: Vehicle,
    state: str,
    priority_slider: int,
    core_mode: str,
    user_inputs: Dict[str, Any],
    budget_min: Optional[int] = None,
    budget_max: Optional[int] = None,
    current_vehicle_annual_cost: Optional[int] = None,
    category_metrics_cache: Optional[Dict[str, Dict[str, list]]] = None
) -> dict:

    if vehicle.powertrain_type == PowertrainType.FCEV:
        return {
            "core_rating": None,
            "message": "CORE Rating not available for hydrogen vehicles at launch.",
            "is_estimate": True
        }

    # priority_slider is retained for API compatibility. The fixed-band path
    # uses mode-specific star ratings from the workbook; non-catalogue vehicles
    # (GVG / legacy / manual entry) do not receive a CORE score per spec §4.
    _ = priority_slider

    state = (state or 'NSW').upper()
    fcai_category = vehicle.fcai_category

    # Target vehicle breakdown and stored workbook data.
    stored_target = _get_stored_mode_data(vehicle, state, core_mode)
    breakdown = calculate_vehicle_cost_breakdown(vehicle, state, core_mode, user_inputs)
    total_cost = breakdown['total_annual']

    # Load / cache peers for distribution and fallback scoring.
    if category_metrics_cache is not None and fcai_category in category_metrics_cache:
        peers = category_metrics_cache[fcai_category].get("peers", [])
    else:
        peers = list(get_vehicles_by_fcai_category(fcai_category))
        if category_metrics_cache is not None:
            category_metrics_cache[fcai_category] = {"peers": peers}

    peer_costs = []
    peer_co2 = []
    peer_powertrains = []
    peer_breakdowns = []
    peer_stored = []

    peer_user_inputs = {
        k: v for k, v in user_inputs.items()
        if k not in ('driveaway_override', 'loan_amount', 'insurance_override')
    }

    for peer in peers:
        peer_br = calculate_vehicle_cost_breakdown(peer, state, core_mode, peer_user_inputs)
        peer_breakdowns.append(peer_br)
        peer_costs.append(peer_br['total_annual'])
        peer_co2.append(peer.tailpipe_co2_g_per_km or 0)
        peer_powertrains.append(peer.powertrain_type)
        peer_stored.append(_get_stored_mode_data(peer, state, core_mode))

    # ----- FIXED-BAND PATH (Carreb workbook vehicles) -----
    if stored_target:
        core_rating, co2_cap_applied, co2_cap_threshold = _apply_star_co2_cap(
            stored_target['stars'],
            vehicle.powertrain_type,
            vehicle.tailpipe_co2_g_per_km
        )
        core_rating = float(core_rating)
        total_annual_cost = int(round(stored_target['mode_coo_pa'] * 100))
        annual_co2_kg = int(round(stored_target['annual_co2_kg']))

    else:
        # ----- NON-CATALOGUE PATH (GVG / legacy / manual entry) -----
        # Per spec §4, current/older vehicles get NO CORE score — raw cost only.
        core_rating = None
        co2_cap_applied = False
        co2_cap_threshold = None
        total_annual_cost = total_cost

        annual_km = user_inputs.get('annual_km', vehicle.annual_km_default or 13300)
        tailpipe_co2 = vehicle.tailpipe_co2_g_per_km or 0
        annual_co2_kg = int((tailpipe_co2 * annual_km) / 1000)

    # Estimated cost difference vs current vehicle or category average.
    def _build_est_cost_diff_obj(baseline: int, total: int, is_current_vehicle: bool) -> dict:
        diff = baseline - total
        comp_mode = "current_vehicle" if is_current_vehicle else "category_avg"
        if is_current_vehicle:
            base_disp = f"Est. ${int(round(baseline / 100)):,}/year"
        else:
            base_disp = f"Est. ${int(round(baseline / 100)):,}/year\n      ({fcai_category} category average)"

        if diff < 0:
            direction = "more_expensive"
            val = abs(diff)
            bucket = None
        elif diff > 0:
            direction = "saving"
            val = diff
            s5 = val * 5
            if s5 < 250000: bucket = "essentials_covered"
            elif s5 < 750000: bucket = "home_family"
            elif s5 < 1250000: bucket = "savings_security"
            else: bucket = "future_proof"
        else:
            direction = "same"
            val = 0
            bucket = None

        s5 = val * 5
        return {
            "value_cents": val,
            "value_display": f"Est. ${int(round(val / 100)):,}/year",
            "direction": direction,
            "comparison_mode": comp_mode,
            "baseline_cost": baseline,
            "baseline_cost_display": base_disp,
            "est_5yr_savings": s5,
            "est_5yr_savings_display": f"Est. ${int(round(s5 / 100)):,} over 5 years",
            "savings_bucket": bucket
        }

    if current_vehicle_annual_cost is not None:
        est_cost_difference = _build_est_cost_diff_obj(current_vehicle_annual_cost, total_annual_cost, True)
    else:
        avg_class_cost = sum(peer_costs) / len(peer_costs) if peer_costs else total_annual_cost
        est_cost_difference = _build_est_cost_diff_obj(int(avg_class_cost), total_annual_cost, False)

    # Calculate peer distribution and medians
    peer_band_stats = {
        "net-zero-ninja": {"count": 0, "breakdowns": [], "co2": [], "totals": []},
        "smart-move": {"count": 0, "breakdowns": [], "co2": [], "totals": []},
        "steady-cruiser": {"count": 0, "breakdowns": [], "co2": [], "totals": []},
        "the-detour": {"count": 0, "breakdowns": [], "co2": [], "totals": []},
        "captain-carbon": {"count": 0, "breakdowns": [], "co2": [], "totals": []}
    }

    annual_km = user_inputs.get('annual_km', vehicle.annual_km_default or 13300)

    for p_cost, p_co2, p_pt, p_br, p_stored in zip(peer_costs, peer_co2, peer_powertrains, peer_breakdowns, peer_stored):
        if p_pt == PowertrainType.FCEV:
            continue

        # Budget filtering check
        driveaway = p_br.get('driveaway_price', 0)
        if budget_min is not None and driveaway < budget_min:
            continue
        if budget_max is not None and driveaway > budget_max:
            continue

        if not p_stored:
            # Peer lacks scored workbook data; do not count it in the
            # distribution because percentile scoring is prohibited.
            continue

        p_rating, _, _ = _apply_star_co2_cap(
            p_stored['stars'],
            p_pt,
            p_co2
        )
        p_total = int(round(p_stored['mode_coo_pa'] * 100))
        p_annual_co2 = int(round(p_stored['annual_co2_kg']))

        p_rating = max(1.0, min(5.0, float(p_rating)))
        band_slug = get_band_slug(p_rating)

        peer_band_stats[band_slug]["count"] += 1
        peer_band_stats[band_slug]["breakdowns"].append(p_br)
        peer_band_stats[band_slug]["co2"].append(p_annual_co2)
        peer_band_stats[band_slug]["totals"].append(p_total)

    # Calculate medians for the response
    peer_distribution = {}
    peer_band_medians = {}

    def get_median_or_zero(data: list) -> int:
        if not data: return 0
        return int(statistics.median(data))

    for slug, stats in peer_band_stats.items():
        peer_distribution[slug] = stats["count"]
        if stats["count"] > 0:
            med_total = get_median_or_zero(stats["totals"])
            if current_vehicle_annual_cost is not None:
                med_est_diff = _build_est_cost_diff_obj(current_vehicle_annual_cost, med_total, True)
            else:
                med_est_diff = _build_est_cost_diff_obj(int(avg_class_cost), med_total, False)

            med_co2 = get_median_or_zero(stats["co2"])

            peer_band_medians[slug] = {
                "total_annual_cost": med_total,
                "annual_co2_kg": med_co2,
                "est_cost_difference": med_est_diff,
                "annual_cost_breakdown": {
                    "fuel_or_energy_annual": get_median_or_zero([b["fuel_or_energy_annual"] for b in stats["breakdowns"]]),
                    "insurance_annual": get_median_or_zero([b["insurance_annual"] for b in stats["breakdowns"]]),
                    "ctp_annual": get_median_or_zero([b["ctp_annual"] for b in stats["breakdowns"]]),
                    "registration_annual": get_median_or_zero([b["registration_annual"] for b in stats["breakdowns"]]),
                    "servicing_annual": get_median_or_zero([b["servicing_annual"] for b in stats["breakdowns"]]),
                    "tyres_annual": get_median_or_zero([b["tyres_annual"] for b in stats["breakdowns"]]),
                    "ev_levy_annual": get_median_or_zero([b["ev_levy_annual"] for b in stats["breakdowns"]]),
                    "other_annual": get_median_or_zero([b["other_annual"] for b in stats["breakdowns"]]),
                    "finance_annual": get_median_or_zero([b["finance_annual"] for b in stats["breakdowns"]]),
                    "resale_credit_annual": get_median_or_zero([b["resale_credit_annual"] for b in stats["breakdowns"]]),
                }
            }
        else:
            peer_band_medians[slug] = None

    result = {
        "core_rating": float(core_rating) if core_rating is not None else None,
        "band_name": get_band_name(core_rating),
        "band_slug": get_band_slug(core_rating),
        "co2_cap_applied": co2_cap_applied,
        "co2_cap_threshold": float(co2_cap_threshold) if co2_cap_threshold else None,
        "annual_cost_breakdown": breakdown,
        "total_annual_cost": total_annual_cost,
        "est_cost_difference": est_cost_difference,
        "tailpipe_co2_g_per_km": float(vehicle.tailpipe_co2_g_per_km or 0),
        "annual_co2_kg": annual_co2_kg,
        "peer_band_distribution": peer_distribution,
        "peer_band_medians": peer_band_medians,
        "is_estimate": True
    }
    if core_rating is None:
        result["message"] = "CORE Rating is only available for Carreb catalogue vehicles."
    return result
