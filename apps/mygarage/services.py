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


def _get_ordinal(n):
    if 11 <= (n % 100) <= 13:
        suffix = 'th'
    else:
        suffix = ['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]
    return str(n) + suffix

def calculate_spotlights(active_garage_vehicles, user_priority_state, state, current_cost):
    if not active_garage_vehicles:
        return {}
        
    user = active_garage_vehicles[0].user
    
    # We shouldn't reach here if user is on FREE, but safe to check
    if user.subscription_tier == SubscriptionTier.FREE:
        return {}
        
    results = {str(gv.id): {} for gv in active_garage_vehicles}
    
    # Pre-group active vehicles by category
    by_category = {}
    for gv in active_garage_vehicles:
        cat = gv.vehicle_catalogue.fcai_category
        if cat:
            by_category.setdefault(cat, []).append(gv)
            
    # Calculate category badges
    priority = user_priority_state.priority_slider_position
    mode = user_priority_state.active_core_mode
    budget = user_priority_state.budget_max
    
    for cat, gvs in by_category.items():
        peers = list(Vehicle.objects.filter(fcai_category=cat))
        ranges = sorted([p.wltp_range_km for p in peers if p.wltp_range_km is not None], reverse=True)
        
        peer_costs = []
        peer_co2 = []
        for p in peers:
            cost_5yr = p.total_5yr_cost_of_ownership_by_state.get(state)
            if cost_5yr:
                peer_costs.append(cost_5yr / 5.0)
            peer_co2.append(p.tailpipe_co2_g_per_km if p.tailpipe_co2_g_per_km is not None else 0)
                
        peer_costs.sort()
        peer_co2.sort()
        
        def is_top_20_percent_lowest(val, sorted_list):
            if not sorted_list or val is None: return False
            if len(sorted_list) < 5:
                return val == sorted_list[0]
            idx = sum(1 for v in sorted_list if v < val)
            return (idx / len(sorted_list)) <= 0.20
            
        def is_top_20_percent_highest(val, sorted_list):
            if not sorted_list or val is None: return False
            if len(sorted_list) < 5:
                return val == sorted_list[-1]
            idx = sum(1 for v in sorted_list if v > val)
            return (idx / len(sorted_list)) <= 0.20
            
        ranges_asc = sorted([p.wltp_range_km for p in peers if p.wltp_range_km is not None])
        
        gvs_ratings = {}
        highest_rating = -1
        for gv in gvs:
            res = calculate_core_rating(gv.vehicle_catalogue, state, priority, mode, {})
            r = res.get('core_rating', 0) or 0
            gvs_ratings[gv.id] = r
            if r > highest_rating:
                highest_rating = r
                
        for gv in gvs:
            vehicle = gv.vehicle_catalogue
            vehicle_data = {
                "id": str(vehicle.id),
                "brand": vehicle.brand,
                "model": vehicle.model,
                "year": vehicle.year,
                "variant": vehicle.variant,
                "powertrain_type": vehicle.powertrain_type,
                "body_style": vehicle.body_style,
                "num_seats": vehicle.num_seats,
                "image_url": vehicle.image_url,
            }
            vid = str(gv.id)
            
            # Range Kings
            my_range = vehicle.wltp_range_km
            if my_range is not None:
                if my_range in ranges[:3]:
                    rank = ranges.index(my_range) + 1
                    results[vid]['range_kings'] = {
                        "badge_name": "Range Kings™",
                        "badge_slug": "range_kings",
                        "earned": True,
                        "reason": f"Top {_get_ordinal(rank)} in {cat} by driving range among your saved vehicles"
                    }
                    
            # Green & Lean
            my_cost_res = calculate_core_rating(vehicle, state, priority, "pure_cost", {})
            my_cost_5yr = vehicle.total_5yr_cost_of_ownership_by_state.get(state)
            my_cost = (my_cost_5yr / 5.0) if my_cost_5yr else my_cost_res['total_annual_cost']
            my_co2 = vehicle.tailpipe_co2_g_per_km if vehicle.tailpipe_co2_g_per_km is not None else 0
            
            if is_top_20_percent_lowest(my_co2, peer_co2) and is_top_20_percent_lowest(my_cost, peer_costs):
                results[vid]['green_and_lean'] = {
                    "badge_name": "Green & Lean™",
                    "badge_slug": "green_and_lean",
                    "earned": True,
                    "reason": f"Low emissions and low estimated running cost in {cat} among your saved vehicles"
                }
                
            # Unicorn Match
            fits_budget = True
            if budget is not None:
                driveaway = vehicle.driveaway_price_by_state.get(state, 0)
                if driveaway > budget:
                    fits_budget = False
            
            if my_range is not None and is_top_20_percent_highest(my_range, ranges_asc) and is_top_20_percent_lowest(my_co2, peer_co2) and fits_budget:
                results[vid]['unicorn_match'] = {
                    "badge_name": "Unicorn Match™",
                    "badge_slug": "unicorn_match",
                    "earned": True,
                    "reason": f"Strong range, low emissions, and fits your budget in {cat} among your saved vehicles"
                }
                
            # Category Sweep
            if highest_rating > 0 and gvs_ratings[gv.id] == highest_rating:
                results[vid]['category_sweep'] = {
                    "badge_name": "Category Sweep™",
                    "badge_slug": "category_sweep",
                    "earned": True,
                    "reason": f"Highest CORE Rating in {cat} among your saved vehicles"
                }
                
    # CORE All-Stars via internal batch endpoint request
    from apps.vehicles.views import CoreRatingBatchView
    from rest_framework.test import APIRequestFactory
    import json
    
    factory = APIRequestFactory()
    vehicle_ids = [str(gv.vehicle_catalogue_id) for gv in active_garage_vehicles]
    all_stars_scores = {str(gv.id): True for gv in active_garage_vehicles}
    
    modes = ['pure_cost', 'cool_choice', 'true_value', 'full_picture']
    for m in modes:
        payload = {
            "vehicle_ids": vehicle_ids,
            "state": state,
            "priority_slider": priority,
            "core_mode": m,
            "current_vehicle_annual_cost": current_cost
        }
        request = factory.post('/api/core-rating/batch/', data=json.dumps(payload), content_type='application/json')
        request.user = user
        response = CoreRatingBatchView.as_view()(request)
        if response.status_code == 200:
            data_list = response.data.get('data', [])
            score_map = {str(d['vehicle_id']): (d.get('core_rating', 0) or 0) for d in data_list}
            for gv in active_garage_vehicles:
                v_cat_id = str(gv.vehicle_catalogue_id)
                rating = score_map.get(v_cat_id, 0)
                if rating < 4.0:
                    all_stars_scores[str(gv.id)] = False
        else:
            for gv in active_garage_vehicles:
                all_stars_scores[str(gv.id)] = False
                
    for gv in active_garage_vehicles:
        vid = str(gv.id)
        if all_stars_scores[vid]:
            results[vid]['core_all_stars'] = {
                "badge_name": "CORE All-Stars™",
                "badge_slug": "core_all_stars",
                "earned": True,
                "reason": "Scores 4★ or above across all four CORE views"
            }
            
    return results


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
