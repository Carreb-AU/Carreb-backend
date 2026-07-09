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
            
    mode = user_priority_state.active_core_mode
    priority = user_priority_state.priority_slider_position
    
    peer_costs = []
    peer_co2 = []
    for p in peers:
        cost_5yr = p.total_5yr_cost_of_ownership_by_state.get(state)
        if cost_5yr:
            peer_costs.append(cost_5yr / 5.0)
            
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
    # Use the same base cost as peer_costs to ensure an apples-to-apples percentile comparison
    my_cost_5yr = vehicle.total_5yr_cost_of_ownership_by_state.get(state)
    my_cost = (my_cost_5yr / 5.0) if my_cost_5yr else my_cost_res['total_annual_cost']
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


import logging
import requests
import math
from django.core.cache import cache
from django.conf import settings
from django.utils.text import slugify

logger = logging.getLogger(__name__)

PLACES_TEXT_URL = 'https://maps.googleapis.com/maps/api/place/textsearch/json'

BRAND_LOCATORS = {
    'toyota': 'https://www.toyota.com.au/find-dealer',
    'mazda': 'https://www.mazda.com.au/find-a-dealer/',
    'hyundai': 'https://www.hyundai.com/au/en/find-a-dealer',
    'ford': 'https://www.ford.com.au/locate-a-dealer/',
    'mitsubishi': 'https://www.mitsubishi-motors.com.au/dealer-locator.html',
    'kia': 'https://www.kia.com.au/find-a-dealer',
    'mg': 'https://mgmotor.com.au/find-a-dealer/',
    'subaru': 'https://www.subaru.com.au/find-a-dealer',
    'tesla': 'https://www.tesla.com/findus',
    'byd': 'https://bydautomotive.com.au/dealer-locator',
    'nissan': 'https://www.nissan.com.au/find-a-dealer.html',
    'volkswagen': 'https://www.volkswagen.com.au/en/find-a-dealer.html',
    'honda': 'https://www.honda.com.au/owners/find-a-dealer',
    'bmw': 'https://www.bmw.com/en-au/fast-lane/dealer-locator.html',
    'mercedes-benz': 'https://www.mercedes-benz.com.au/passengercars/mercedes-benz-cars/dealer-locator.html',
    'audi': 'https://www.audi.com.au/au/web/en/dealer-locator.html',
    'lexus': 'https://www.lexus.com.au/contact/find-a-dealer',
    'volvo': 'https://www.volvocars.com/au/dealers',
    'jeep': 'https://www.jeep.com.au/find-a-dealer.html',
    'land-rover': 'https://www.landrover.com.au/dealer-locator.html',
    'jaguar': 'https://www.jaguar.com.au/dealer-locator.html',
    'porsche': 'https://www.porsche.com/australia/aboutporsche/porschecentres/',
    'suzuki': 'https://www.suzuki.com.au/find-a-dealer',
    'isuzu': 'https://www.isuzuute.com.au/find-a-dealer',
    'gwm': 'https://www.gwmhaval.com.au/find-a-dealer',
    'haval': 'https://www.gwmhaval.com.au/find-a-dealer',
    'cupra': 'https://www.cupraofficial.com.au/dealer-locator',
    'skoda': 'https://www.skoda.com.au/dealer-locator/dealer-search',
    'polestar': 'https://www.polestar.com/au/spaces/',
    'ldv': 'https://www.ldvautomotive.com.au/find-a-dealer/',
    'chery': 'https://cherymotor.com.au/find-a-dealer/',
}

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_postcode_coords(postcode: str, api_key: str) -> tuple:
    cache_key = f"postcode_coords:{postcode}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    params = {
        'query': f'{postcode}, Australia',
        'key': api_key,
    }
    try:
        resp = requests.get(PLACES_TEXT_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') == 'OK' and data.get('results'):
            loc = data['results'][0]['geometry']['location']
            coords = (loc['lat'], loc['lng'])
            cache.set(cache_key, coords, 86400 * 30)  # 30 days
            return coords
    except Exception as e:
        logger.exception("Failed to geocode postcode %s: %s", postcode, e)
    return None, None

def search_dealers_external(brand: str, postcode: str, radius_km: int) -> dict:
    api_key = getattr(settings, 'GOOGLE_PLACES_API_KEY', None)
    if not api_key:
        logger.error("GOOGLE_PLACES_API_KEY is not configured in settings.")
        return {
            'results': [],
            'service_unavailable': True,
            'message': "Dealer search is temporarily unavailable. Please try again shortly."
        }

    # First, get postcode coordinates
    lat, lng = get_postcode_coords(postcode, api_key)
    if lat is None or lng is None:
        return {
            'results': [],
            'service_unavailable': False,
        }

    # Query Google Places Text Search
    query = f'{brand} dealer'
    params = {
        'query': f'{query} near {postcode}, Australia',
        'radius': radius_km * 1000,  # meters
        'type': 'car_dealer',
        'region': 'au',
        'key': api_key,
    }

    try:
        resp = requests.get(PLACES_TEXT_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.exception("Google Places API call failed: %s", e)
        return {
            'results': [],
            'service_unavailable': True,
            'message': "Dealer search is temporarily unavailable. Please try again shortly."
        }

    status = data.get('status')
    if status not in ('OK', 'ZERO_RESULTS'):
        logger.warning("Google Places returned unexpected status %s: %s", status, data.get('error_message'))
        if status in ('OVER_QUERY_LIMIT', 'REQUEST_DENIED', 'INVALID_REQUEST'):
            return {
                'results': [],
                'service_unavailable': True,
                'message': "Dealer search is temporarily unavailable. Please try again shortly."
            }
        return {
            'results': [],
            'service_unavailable': False,
        }

    raw_results = data.get('results', [])
    dealers = []
    for r in raw_results:
        location = r.get('geometry', {}).get('location', {})
        d_lat = location.get('lat')
        d_lng = location.get('lng')
        
        if d_lat is None or d_lng is None:
            continue
            
        dist = haversine_distance(lat, lng, d_lat, d_lng)
        
        # Filter by radius manually to be precise
        if dist <= radius_km:
            place_id = r.get('place_id')
            dealers.append({
                'dealer_name': r.get('name'),
                'distance_km': round(dist, 1),
                'website_url': f'https://www.google.com/maps/place/?q=place_id:{place_id}' if place_id else '',
                'external_link_notice': "You will leave Carreb and the dealer's own terms and privacy policy will apply."
            })

    # Sort by distance and return top 5
    dealers.sort(key=lambda x: x['distance_km'])
    results = dealers[:5]

    return {
        'results': results,
        'service_unavailable': False,
    }

def get_dealers(brand: str, postcode: str, radius_km: int) -> dict:
    brand_slug = slugify(brand)
    cache_key = f"find_a_dealer:{brand_slug}:{postcode}:{radius_km}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    res = search_dealers_external(brand, postcode, radius_km)
    
    # Cache only if service is NOT unavailable
    if not res.get('service_unavailable'):
        cache.set(cache_key, res, 86400) # 24 hours
        
    return res
