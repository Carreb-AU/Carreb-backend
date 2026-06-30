from apps.mygarage.models import GarageVehicle, GarageVehicleStatus
from apps.users.models import SubscriptionTier
from apps.vehicles.models import Vehicle
from apps.vehicles.services.rating_engine import calculate_core_rating

PLAN_LIMITS = {
    SubscriptionTier.FREE: 1,
    SubscriptionTier.CAR_BUYING_SPRINT: 3,
    SubscriptionTier.CORE_ADVANTAGE: 10,
    SubscriptionTier.FULL_INSIGHT_PRO: 30
}

def get_user_garage_limit(user):
    return PLAN_LIMITS.get(user.subscription_tier, 1)

def get_cap_counter(user):
    limit = get_user_garage_limit(user)
    current_count = GarageVehicle.objects.filter(
        user=user,
        status__in=[GarageVehicleStatus.ACTIVE, GarageVehicleStatus.ARCHIVED]
    ).count()
    
    plan_name = dict(SubscriptionTier.choices).get(user.subscription_tier, "Free Starter")
    return {
        "used": current_count,
        "limit": limit,
        "plan": plan_name
    }

def check_cap_limit(user):
    limit = get_user_garage_limit(user)
    current_count = GarageVehicle.objects.filter(
        user=user,
        status__in=[GarageVehicleStatus.ACTIVE, GarageVehicleStatus.ARCHIVED]
    ).count()
    return current_count < limit


def calculate_spotlights(garage_vehicle, user_priority_state, state, current_cost, active_garage_vehicles):
    user = garage_vehicle.user
    if user.subscription_tier == SubscriptionTier.FREE:
        return None # Free tier does not get spotlights
        
    vehicle = garage_vehicle.vehicle_catalogue
    
    # 1. Gather peer data
    peers = list(Vehicle.objects.filter(fcai_category=vehicle.fcai_category))
    
    # For range kings (top 3 highest range)
    ranges = sorted([p.wltp_range_km for p in peers if p.wltp_range_km is not None], reverse=True)
    is_range_king = False
    if vehicle.wltp_range_km is not None:
        if vehicle.wltp_range_km in ranges[:3]:
            is_range_king = True
            
    # Calculate costs for peers (using pure_cost as baseline or current mode)
    # The requirement doesn't specify which mode to use for green_and_lean cost comparison,
    # so we use the user's current mode.
    mode = user_priority_state.active_core_mode
    priority = user_priority_state.priority_slider_position
    
    # We need to evaluate total_annual_cost for all peers
    peer_costs = []
    peer_co2 = []
    for p in peers:
        res = calculate_core_rating(p, state, priority, mode, {})
        peer_costs.append(res['total_annual_cost'])
        if p.tailpipe_co2_g_per_km is not None:
            peer_co2.append(p.tailpipe_co2_g_per_km)
            
    peer_costs.sort()
    peer_co2.sort()
    
    def is_top_20_percent_lowest(val, sorted_list):
        if not sorted_list or val is None: return False
        idx = sum(1 for v in sorted_list if v < val)
        return (idx / len(sorted_list)) <= 0.20
        
    def is_top_20_percent_highest(val, sorted_list): # sorted_list is sorted ascending
        if not sorted_list or val is None: return False
        idx = sum(1 for v in sorted_list if v > val)
        return (idx / len(sorted_list)) <= 0.20

    my_cost_res = calculate_core_rating(vehicle, state, priority, mode, {})
    my_cost = my_cost_res['total_annual_cost']
    my_co2 = vehicle.tailpipe_co2_g_per_km
    my_range = vehicle.wltp_range_km
    
    is_green_and_lean = is_top_20_percent_lowest(my_co2, peer_co2) and is_top_20_percent_lowest(my_cost, peer_costs)
    
    ranges_asc = sorted([p.wltp_range_km for p in peers if p.wltp_range_km is not None])
    fits_budget = True
    if user_priority_state.budget_max is not None:
        driveaway = vehicle.driveaway_price_by_state.get(state, 0)
        if driveaway > user_priority_state.budget_max:
            fits_budget = False
            
    is_unicorn_match = is_top_20_percent_highest(my_range, ranges_asc) and is_top_20_percent_lowest(my_co2, peer_co2) and fits_budget
    
    # Category Sweep
    is_category_sweep = False
    my_rating = my_cost_res.get('core_rating', 0) or 0
    
    # Check other active garage vehicles in same category
    same_cat_active = [gv for gv in active_garage_vehicles if gv.vehicle_catalogue.fcai_category == vehicle.fcai_category]
    highest_rating = 0
    for gv in same_cat_active:
        res = calculate_core_rating(gv.vehicle_catalogue, state, priority, mode, {})
        r = res.get('core_rating', 0) or 0
        if r > highest_rating:
            highest_rating = r
            
    if my_rating >= highest_rating and my_rating > 0 and len(same_cat_active) > 0:
        # Check if it's strictly the single highest or ties allowed. Requirement: "single highest"
        # We'll just count how many have the highest
        winners = 0
        for gv in same_cat_active:
            res = calculate_core_rating(gv.vehicle_catalogue, state, priority, mode, {})
            if (res.get('core_rating', 0) or 0) == highest_rating:
                winners += 1
        if winners == 1 and my_rating == highest_rating:
            is_category_sweep = True

    # Core All Stars
    modes = ['pure_cost', 'cool_choice', 'true_value', 'full_picture']
    is_core_all_stars = True
    for m in modes:
        res = calculate_core_rating(vehicle, state, priority, m, {})
        rating = res.get('core_rating', 0) or 0
        if rating < 4.0:
            is_core_all_stars = False
            break
            
    badges = {}
    if is_range_king: badges['range_kings'] = True
    if is_green_and_lean: badges['green_and_lean'] = True
    if is_unicorn_match: badges['unicorn_match'] = True
    if is_category_sweep: badges['category_sweep'] = True
    if is_core_all_stars: badges['core_all_stars'] = True
    
    return badges if badges else None
