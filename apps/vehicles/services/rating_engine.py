from typing import Dict, Any, Optional
from decimal import Decimal
import math
from django.utils import timezone
from apps.vehicles.models import Vehicle, PowertrainType

# Trademarked Band Names
BAND_NAMES = {
    (4.5, 5.0): "Net Zero Ninja™",
    (3.5, 4.4): "Smart Move™",
    (2.5, 3.4): "Steady Cruiser™",
    (1.5, 2.4): "The Detour™",
    (1.0, 1.4): "Captain Carbon™",
}

def get_band_name(rating: float) -> str:
    for (min_val, max_val), name in BAND_NAMES.items():
        if min_val <= rating <= max_val:
            return name
    return "Captain Carbon™" # Fallback

def get_band_slug(rating: float) -> str:
    if rating >= 4.5: return "net-zero-ninja"
    if rating >= 3.5: return "smart-move"
    if rating >= 2.5: return "steady-cruiser"
    if rating >= 1.5: return "the-detour"
    return "captain-carbon"

def calculate_monthly_repayment(principal: float, annual_rate: float, months: int) -> float:
    if annual_rate == 0:
        return principal / months
    monthly_rate = (annual_rate / 100.0) / 12
    repayment = principal * (monthly_rate * math.pow(1 + monthly_rate, months)) / (math.pow(1 + monthly_rate, months) - 1)
    return repayment

def _get_state_value(json_field: dict, state: str, default_val=0) -> int:
    if not json_field: return default_val
    return json_field.get(state, default_val)

def calculate_vehicle_cost_breakdown(
    vehicle: Vehicle,
    state: str,
    core_mode: str,
    user_inputs: Dict[str, Any]
) -> Dict[str, Any]:
    
    annual_km = user_inputs.get('annual_km', vehicle.annual_km_default or 13300)
    
    driveaway = user_inputs.get('driveaway_override')
    if not driveaway:
        driveaway = _get_state_value(vehicle.driveaway_price_by_state, state)
    
    # 1. Fuel / Energy
    # Simplified calculation: (consumption / 100) * annual_km * cost_per_unit
    # Assuming $2.00 per L for fuel and $0.30 per kWh for electricity for this simplified logic
    fuel_annual = 0
    if vehicle.fuel_consumption_per_100km:
        fuel_annual = (vehicle.fuel_consumption_per_100km / 100) * annual_km * 200 # cents
    if vehicle.electricity_consumption_per_100km:
        fuel_annual += (vehicle.electricity_consumption_per_100km / 100) * annual_km * 30 # cents
        
    fuel_annual = int(fuel_annual)
    
    # 2. Insurance
    insurance = user_inputs.get('insurance_override')
    if not insurance:
        insurance = _get_state_value(vehicle.insurance_estimate_by_state, state)
    
    ctp = _get_state_value(vehicle.ctp_by_state, state)
    rego = _get_state_value(vehicle.registration_by_state, state)
    
    servicing_annual = int((vehicle.servicing_5yr_estimate or 0) / 5)
    tyres_annual = int((vehicle.tyre_replacement_estimate or 0) / 5)
    
    if not insurance and not ctp and not rego and not servicing_annual and not tyres_annual:
        total_5yr = _get_state_value(vehicle.total_5yr_cost_of_ownership_by_state, state)
        if total_5yr:
            annual_aggregate = int(total_5yr / 5)
            non_fuel_annual = max(0, annual_aggregate - fuel_annual)
            servicing_annual = non_fuel_annual
    
    finance_annual = 0
    if core_mode in ['cool_choice', 'full_picture']:
        loan_amount = user_inputs.get('loan_amount', driveaway * 0.8) # 20% deposit
        interest_rate = user_inputs.get('interest_rate', 7.5)
        loan_term_months = user_inputs.get('loan_term_months', 60)
        monthly = calculate_monthly_repayment(loan_amount / 100.0, interest_rate, loan_term_months)
        finance_annual = int(monthly * 12 * 100)
    
    resale_annual = 0
    if core_mode in ['true_value', 'full_picture']:
        resale_annual = int((vehicle.resale_value_5yr_estimate or 0) / 5)
    
    total = fuel_annual + insurance + ctp + rego + servicing_annual + tyres_annual
    if core_mode in ['cool_choice', 'full_picture']:
        total += finance_annual
    if core_mode in ['true_value', 'full_picture']:
        total -= resale_annual
        
    return {
        "fuel_or_energy_annual": fuel_annual,
        "insurance_annual": insurance,
        "ctp_annual": ctp,
        "registration_annual": rego,
        "servicing_annual": servicing_annual,
        "tyres_annual": tyres_annual,
        "finance_annual": finance_annual if core_mode in ['cool_choice', 'full_picture'] else 0,
        "resale_credit_annual": resale_annual if core_mode in ['true_value', 'full_picture'] else 0,
        "total_annual": total
    }


def get_percentile_score(value: float, category_values: list, reverse=False) -> float:
    if not category_values: return 3.0
    sorted_vals = sorted(category_values)
    
    n = len(sorted_vals)
    worse_count = sum(1 for v in sorted_vals if v > value)
    percentile = worse_count / n # 0.0 to 1.0
    
    if percentile >= 0.9:
        return 4.5 + ((percentile - 0.9) / 0.1) * 0.5
    elif percentile >= 0.7:
        return 3.5 + ((percentile - 0.7) / 0.2) * 0.9
    elif percentile >= 0.3:
        return 2.5 + ((percentile - 0.3) / 0.4) * 0.9
    elif percentile >= 0.1:
        return 1.5 + ((percentile - 0.1) / 0.2) * 0.9
    else:
        return 1.0 + (percentile / 0.1) * 0.4


def calculate_core_rating(
    vehicle: Vehicle,
    state: str,
    priority_slider: int,
    core_mode: str,
    user_inputs: Dict[str, Any],
    current_vehicle_annual_cost: Optional[int] = None
) -> dict:
    
    if vehicle.powertrain_type == PowertrainType.FCEV:
        return {
            "core_rating": None,
            "message": "CORE Rating not available for hydrogen vehicles at launch.",
            "is_estimate": True
        }

    # Weights
    weights = {
        1: (1.0, 0.0),
        2: (0.75, 0.25),
        3: (0.50, 0.50),
        4: (0.25, 0.75),
        5: (0.0, 1.0)
    }
    coo_weight, co2_weight = weights.get(priority_slider, (0.5, 0.5))
    
    breakdown = calculate_vehicle_cost_breakdown(vehicle, state, core_mode, user_inputs)
    total_cost = breakdown['total_annual']
    
    peers = list(Vehicle.objects.filter(fcai_category=vehicle.fcai_category))
    
    peer_costs = []
    peer_co2 = []
    
    for peer in peers:
        peer_br = calculate_vehicle_cost_breakdown(peer, state, core_mode, user_inputs)
        peer_costs.append(peer_br['total_annual'])
        peer_co2.append(peer.tailpipe_co2_g_per_km or 0)
        
    coo_score = get_percentile_score(total_cost, peer_costs)
    co2_score = get_percentile_score(vehicle.tailpipe_co2_g_per_km or 0, peer_co2)
    
    blended_score = round(coo_score * coo_weight + co2_score * co2_weight, 1)
    
    # Apply CO2 Cap
    co2_cap_applied = False
    co2_cap_threshold = None
    
    if vehicle.powertrain_type not in [PowertrainType.BEV, PowertrainType.FCEV]:
        tailpipe = vehicle.tailpipe_co2_g_per_km or 0
        cap = None
        if tailpipe >= 250:
            cap = 2.4
        elif tailpipe >= 200:
            cap = 3.4
        elif tailpipe >= 150:
            cap = 4.4
            
        if cap is not None and blended_score > cap:
            blended_score = cap
            co2_cap_applied = True
            co2_cap_threshold = cap
            
    blended_score = max(1.0, min(5.0, blended_score))
    
    # Est cost difference
    est_cost_difference = None
    if current_vehicle_annual_cost is not None:
        est_cost_difference = current_vehicle_annual_cost - total_cost
    else:
        avg_class_cost = sum(peer_costs) / len(peer_costs) if peer_costs else total_cost
        est_cost_difference = int(avg_class_cost - total_cost)
        
    return {
        "core_rating": float(blended_score),
        "band_name": get_band_name(blended_score),
        "band_slug": get_band_slug(blended_score),
        "co2_cap_applied": co2_cap_applied,
        "co2_cap_threshold": float(co2_cap_threshold) if co2_cap_threshold else None,
        "annual_cost_breakdown": breakdown,
        "total_annual_cost": total_cost,
        "est_cost_difference": est_cost_difference,
        "is_estimate": True
    }
