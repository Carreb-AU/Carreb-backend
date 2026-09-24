from rest_framework import views, status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.utils import timezone
from django.core.cache import cache
from django.db import models, connection
from django.contrib.postgres.search import TrigramSimilarity
from django.shortcuts import get_object_or_404
import statistics
from apps.mygarage.models import (
    CurrentVehicle, GarageVehicle, GarageVehicleStatus, GarageVehicleSource,
    VehicleOverride, UserPriorityState, CoreMode, AISmartMatchRequest
)
from apps.vehicles.models import Vehicle, VehicleIdentity
from apps.vehicles.services.gvg_import import build_vehicle_like_from_gvg
from apps.vehicles.services.image_lookup import get_vehicle_image_url
from apps.users.models import SubscriptionTier
from apps.users.permissions import IsPaidMember
from apps.mygarage.serializers import (
    CurrentVehicleSerializer, GarageVehicleSerializer,
    UserPriorityStateSerializer, CurrentVehicleCreateSerializer,
    GarageVehicleCreateSerializer, VehicleDetailOverrideSerializer,
    AISmartMatchInputSerializer
)
from apps.mygarage.services import check_cap_limit, get_cap_counter, calculate_spotlights
from apps.mygarage.ai_service import (
    extract_search_parameters,
    build_recommendation_reason,
    estimate_engine_displacement,
    estimate_ancap_rating,
    estimate_resale_value,
)
from apps.vehicles.services.rating_engine import calculate_core_rating, _get_state_cents
from apps.vehicles.tasks import emit_analytics_event

def _get_overrides(user, current_vehicle=None, garage_vehicle=None):
    overrides = VehicleOverride.objects.filter(
        user=user, 
        current_vehicle=current_vehicle, 
        garage_vehicle=garage_vehicle
    )
    return {o.field_name: o.override_value for o in overrides}

def _build_calculated_vehicle_response(user, vehicle_instance, priority_state, current_cost=None, is_current_vehicle=False):
    base_data = None
    overrides_qs = None

    if is_current_vehicle:
        base_data = CurrentVehicleSerializer(vehicle_instance).data
        overrides_qs = VehicleOverride.objects.filter(user=user, current_vehicle=vehicle_instance)
        # Current vehicle ALWAYS uses pure cost
        mode = CoreMode.PURE_COST
        priority = 3
        state = vehicle_instance.state or 'NSW'
        catalogue = vehicle_instance.vehicle_catalogue
        gvg_record = vehicle_instance.green_vehicle_guide_record
    else:
        base_data = GarageVehicleSerializer(vehicle_instance).data
        overrides_qs = VehicleOverride.objects.filter(user=user, garage_vehicle=vehicle_instance)
        mode = priority_state.active_core_mode
        priority = priority_state.priority_slider_position
        # Assume state from current vehicle if exists, else default
        cv = getattr(user, 'current_vehicle', None)
        state = cv.state if cv and cv.state else 'NSW'
        catalogue = vehicle_instance.vehicle_catalogue
        gvg_record = None

    if catalogue and base_data:
        base_data['image_url'] = catalogue.image_url
        base_data['year'] = catalogue.year
        base_data['make'] = catalogue.brand
        base_data['model'] = catalogue.model
        base_data['variant'] = catalogue.variant
        base_data['body_style'] = catalogue.body_style
        base_data['powertrain_type'] = catalogue.powertrain_type

    # Build a vehicle-like object for rating. Prefer Carreb catalogue, then GVG record.
    rating_vehicle = catalogue
    if not rating_vehicle and gvg_record:
        rating_vehicle = build_vehicle_like_from_gvg(gvg_record, state)
        base_data = base_data or {}
        base_data['gvg_record_id'] = str(gvg_record.id)
        base_data['year'] = gvg_record.year
        base_data['make'] = gvg_record.make
        base_data['model'] = gvg_record.model
        base_data['variant'] = gvg_record.variant
        base_data['body_style'] = gvg_record.body_style
        base_data['powertrain_type'] = gvg_record.powertrain_type
        base_data['fuel_consumption_per_100km'] = gvg_record.fuel_consumption_combined_l_100km
        base_data['tailpipe_co2_g_per_km'] = gvg_record.tailpipe_co2_g_per_km
        base_data['source'] = 'gvg'

    user_inputs = {o.field_name: o.override_value for o in overrides_qs}

    engine_data = None
    if rating_vehicle:
        engine_data = calculate_core_rating(
            rating_vehicle,
            state,
            priority,
            mode,
            user_inputs,
            current_vehicle_annual_cost=current_cost
        )

    return {
        "vehicle_data": base_data,
        "engine_data": engine_data,
        "overrides": user_inputs,
        "meta": {
            "calculated_at": timezone.now().isoformat(),
            "is_estimate": True,
            "disclaimer": "All figures are estimates only."
        }
    }


def _median_or_none(values):
    return int(statistics.median(values)) if values else None


def _build_dial_bands(user, priority_state):
    """
    Build the band-level numbers the CORE Dial expects.

    Returns a list of band dicts (one per star band) containing:
      - slug: band identifier matching frontend DIAL_MODES ids
      - vehicle_count: number of active garage vehicles in this band
      - coo: median total annual cost ($/year) for vehicles in this band
      - co2: median annual CO2 (kg/year) for vehicles in this band
      - cost_diff: median estimated cost difference vs the current vehicle (cents)
    """
    band_slugs = [
        'captain-carbon',
        'the-detour',
        'steady-cruiser',
        'smart-move',
        'net-zero-ninja',
    ]
    band_stats = {
        slug: {'costs': [], 'co2s': [], 'diffs': [], 'count': 0}
        for slug in band_slugs
    }

    cv = getattr(user, 'current_vehicle', None)
    cv_cost = None
    if cv:
        cv_resp = _build_calculated_vehicle_response(user, cv, priority_state, is_current_vehicle=True)
        cv_cost = cv_resp.get('engine_data', {}).get('total_annual_cost')

    active_qs = GarageVehicle.objects.filter(user=user, status=GarageVehicleStatus.ACTIVE)
    for gv in active_qs:
        resp = _build_calculated_vehicle_response(user, gv, priority_state)
        engine_data = resp.get('engine_data')
        if not engine_data:
            continue
        slug = engine_data.get('band_slug')
        if slug not in band_stats:
            continue

        band_stats[slug]['count'] += 1
        total = engine_data.get('total_annual_cost')
        co2 = engine_data.get('annual_co2_kg')
        if total is not None:
            band_stats[slug]['costs'].append(total)
        if co2 is not None:
            band_stats[slug]['co2s'].append(co2)

        diff_obj = engine_data.get('est_cost_difference')
        diff_cents = None
        if isinstance(diff_obj, dict):
            diff_cents = diff_obj.get('value_cents')
        if diff_cents is not None and cv_cost is not None:
            band_stats[slug]['diffs'].append(diff_cents)

    return [
        {
            'slug': slug,
            'vehicle_count': band_stats[slug]['count'],
            'coo': _median_or_none(band_stats[slug]['costs']),
            'co2': _median_or_none(band_stats[slug]['co2s']),
            'cost_diff': _median_or_none(band_stats[slug]['diffs']),
        }
        for slug in band_slugs
    ]


class CurrentVehicleView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            cv = request.user.current_vehicle
            state = getattr(request.user, 'priority_state', None)
            if not state:
                state = UserPriorityState.objects.create(user=request.user)
            resp = _build_calculated_vehicle_response(request.user, cv, state, is_current_vehicle=True)
            return Response(resp)
        except CurrentVehicle.DoesNotExist:
            return Response(None)
            
    def post(self, request):
        serializer = CurrentVehicleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        vehicle_catalogue_id = data.get('vehicle_catalogue_id')
        exists_in_garage = False
        
        if vehicle_catalogue_id:
            exists_in_garage = GarageVehicle.objects.filter(
                user=request.user,
                vehicle_catalogue_id=vehicle_catalogue_id,
                status=GarageVehicleStatus.ACTIVE
            ).exists()
            
            if not exists_in_garage and not check_cap_limit(request.user):
                cap = get_cap_counter(request.user)
                return Response({
                    "detail": f"Plan limit reached. You are on {cap['plan']} which allows {cap['limit']} vehicles.",
                    "cap_counter": cap
                }, status=status.HTTP_403_FORBIDDEN)
        
        cv, created = CurrentVehicle.objects.update_or_create(
            user=request.user,
            defaults={
                'vehicle_catalogue_id': data.get('vehicle_catalogue_id'),
                'green_vehicle_guide_record_id': data.get('green_vehicle_guide_record_id'),
                'manual_entry_data': data.get('manual_entry_data'),
                'purchase_date': data.get('purchase_date'),
                'licence_plate': data.get('licence_plate'),
                'odometer_reading': data.get('odometer_reading'),
                'state': data.get('state'),
            }
        )
        
        if vehicle_catalogue_id and not exists_in_garage:
            GarageVehicle.objects.create(
                user=request.user,
                vehicle_catalogue_id=vehicle_catalogue_id,
                source=GarageVehicleSource.VEHICLE_LOOKUP
            )
            if getattr(request.user, 'analytics_consent', False):
                emit_analytics_event.delay(str(request.user.id), 'vehicle_added_to_garage', {})
        
        state = getattr(request.user, 'priority_state', None)
        if not state:
            state = UserPriorityState.objects.create(user=request.user)
            
        resp = _build_calculated_vehicle_response(request.user, cv, state, is_current_vehicle=True)
        cache.delete(f"spotlights_{request.user.id}")
        return Response(resp)

class CurrentVehicleSearchView(views.APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def _image_url_for(self, obj, source):
        """Return a usable image URL, looking it up on-demand if missing."""
        if source == 'carreb':
            stored = getattr(obj, 'image_url', None)
            make, model, year = obj.brand, obj.model, obj.year
            fcai_category = getattr(obj, 'fcai_category', None)
            body_style = getattr(obj, 'body_style', None)
            drive = getattr(obj, 'drive', None)
        else:
            stored = getattr(obj, 'image_url', None)
            make, model, year = obj.make, obj.model, obj.year
            fcai_category = getattr(obj, 'fcai_category', None)
            body_style = getattr(obj, 'body_style', None)
            drive = getattr(obj, 'drive', None)

        if stored:
            return stored
        return get_vehicle_image_url(
            make,
            model,
            year=year,
            fcai_category=fcai_category,
            body_style=body_style,
            drive=drive,
            delay=0.05,
        )

    def _normalize_result(self, obj, source):
        """Return a consistent shape for catalogue and GVG records."""
        image_url = self._image_url_for(obj, source)
        if source == 'carreb':
            return {
                "id": str(obj.id),
                "source": "carreb",
                "year": obj.year,
                "make": obj.brand,
                "model": obj.model,
                "variant": obj.variant,
                "body_style": obj.body_style,
                "powertrain_type": obj.powertrain_type,
                "fuel_consumption_per_100km": obj.fuel_consumption_per_100km,
                "electricity_consumption_per_100km": obj.electricity_consumption_per_100km,
                "tailpipe_co2_g_per_km": obj.tailpipe_co2_g_per_km,
                "image_url": image_url,
                "name": str(obj),
            }
        return {
            "id": str(obj.id),
            "source": "gvg",
            "year": obj.year,
            "make": obj.make,
            "model": obj.model,
            "variant": obj.variant,
            "body_style": obj.body_style,
            "powertrain_type": obj.powertrain_type,
            "fuel_consumption_per_100km": obj.fuel_consumption_combined_l_100km,
            "electricity_consumption_per_100km": (
                obj.electricity_consumption_wh_per_km / 10.0
                if obj.electricity_consumption_wh_per_km else None
            ),
            "tailpipe_co2_g_per_km": obj.tailpipe_co2_g_per_km,
            "image_url": image_url,
            "name": f"{obj.year} {obj.make} {obj.model} {obj.variant}".strip(),
        }

    def post(self, request):
        import re
        query = (request.data.get('query') or '').strip()
        if not query:
            return Response([])

        # Tokenise: a 4-digit token filters year; the rest match brand/model/variant.
        year_match = re.search(r'\b(19|20)\d{2}\b', query)
        year = int(year_match.group()) if year_match else None
        words = [w for w in re.sub(r'\b(19|20)\d{2}\b', ' ', query).split() if w]

        def text_filter(qs, brand_field='brand', model_field='model'):
            for w in words:
                qs = qs.filter(
                    models.Q(**{f'{brand_field}__icontains': w}) |
                    models.Q(**{f'{model_field}__icontains': w})
                )
            return qs

        results, seen = [], set()

        def identity_key(brand, model_name, variant, yr):
            return ((brand or '').casefold(), (model_name or '').casefold(),
                    (variant or '').casefold(), yr)

        # 1. Carreb catalogue (new vehicles; preferred on collision)
        carreb_qs = text_filter(Vehicle.objects.all(), brand_field='brand', model_field='model')
        if year:
            carreb_qs = carreb_qs.filter(year=year)
        for v in carreb_qs.order_by('brand', 'model', '-year')[:10]:
            seen.add(identity_key(v.brand, v.model, v.variant, v.year))
            results.append(self._normalize_result(v, 'carreb'))

        # 2. GVG records (older vehicles) - trigram fuzzy type-ahead
        if len(results) < 10:
            gvg_qs = VehicleIdentity.objects.all()
            if connection.vendor == 'postgresql':
                needle = (' '.join(([str(year)] if year else []) + words) or query).lower()
                gvg_qs = gvg_qs.annotate(
                    sim=TrigramSimilarity('search_text', needle)
                ).filter(sim__gt=0.05).order_by('-sim', '-year')
                if year:
                    gvg_qs = gvg_qs.filter(year=year)
            else:
                # Fallback for SQLite/development
                gvg_qs = text_filter(gvg_qs, brand_field='make', model_field='model')
                if year:
                    gvg_qs = gvg_qs.filter(year=year)
                gvg_qs = gvg_qs.order_by('make', 'model', '-year')

            for r in gvg_qs[:20]:
                if len(results) >= 10:
                    break
                key = identity_key(r.make, r.model, r.variant, r.year)
                if key in seen:
                    continue
                seen.add(key)
                results.append(self._normalize_result(r, 'gvg'))

        return Response(results)

class CurrentVehicleDetailsView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def patch(self, request):
        try:
            cv = request.user.current_vehicle
        except CurrentVehicle.DoesNotExist:
            return Response({"detail": "No current vehicle set"}, status=status.HTTP_404_NOT_FOUND)
            
        serializer = VehicleDetailOverrideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        VehicleOverride.objects.update_or_create(
            user=request.user,
            current_vehicle=cv,
            field_name=serializer.validated_data['field_name'],
            defaults={'override_value': serializer.validated_data['override_value']}
        )
        
        if getattr(request.user, 'analytics_consent', False):
            emit_analytics_event.delay(str(request.user.id), 'vehicle_field_overridden', {'field_name': serializer.validated_data['field_name']})
            
        state = getattr(request.user, 'priority_state', None)
        cache.delete(f"spotlights_{request.user.id}")
        return Response(_build_calculated_vehicle_response(request.user, cv, state, is_current_vehicle=True))

class CurrentVehicleOverrideDeleteView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def delete(self, request, field_name):
        try:
            cv = request.user.current_vehicle
        except CurrentVehicle.DoesNotExist:
            return Response({"detail": "No current vehicle set"}, status=status.HTTP_404_NOT_FOUND)
            
        deleted, _ = VehicleOverride.objects.filter(user=request.user, current_vehicle=cv, field_name=field_name).delete()
        if not deleted:
            return Response({"detail": "Override not found"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            
        state = getattr(request.user, 'priority_state', None)
        cache.delete(f"spotlights_{request.user.id}")
        return Response(_build_calculated_vehicle_response(request.user, cv, state, is_current_vehicle=True))

class CurrentVehicleAutoFillView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        section = request.data.get('section')
        if section not in ['technical_details', 'vehicle_costs', 'finance']:
            return Response({"detail": "Invalid section"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            cv = request.user.current_vehicle
        except CurrentVehicle.DoesNotExist:
            return Response({"detail": "No current vehicle set"}, status=status.HTTP_404_NOT_FOUND)

        # Resolve the vehicle record (Carreb catalogue preferred, then GVG).
        rating_vehicle = cv.vehicle_catalogue
        gvg_record = cv.green_vehicle_guide_record
        if not rating_vehicle and gvg_record:
            rating_vehicle = build_vehicle_like_from_gvg(gvg_record, cv.state or 'NSW')

        if not rating_vehicle:
            return Response({"detail": "No vehicle data available"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        suggested_values = {}
        badges = {}

        if section == 'technical_details':
            if getattr(rating_vehicle, 'engine_l', None) is None:
                estimated = estimate_engine_displacement(
                    make=getattr(rating_vehicle, 'brand', '') or getattr(rating_vehicle, 'make', ''),
                    model=getattr(rating_vehicle, 'model', ''),
                    variant=getattr(rating_vehicle, 'variant', ''),
                    year=getattr(rating_vehicle, 'year', 0) or 0,
                )
                if estimated:
                    suggested_values['engine_l'] = estimated
                    badges['engine_l'] = {"source": "AI est.", "category": "technical_details"}

            if getattr(rating_vehicle, 'ancap_safety_rating', None) is None:
                estimated = estimate_ancap_rating(
                    make=getattr(rating_vehicle, 'brand', '') or getattr(rating_vehicle, 'make', ''),
                    model=getattr(rating_vehicle, 'model', ''),
                    year=getattr(rating_vehicle, 'year', 0) or 0,
                )
                if estimated:
                    suggested_values['ancap_safety_rating'] = estimated
                    badges['ancap_safety_rating'] = {"source": "AI est.", "category": "technical_details"}

        elif section == 'vehicle_costs':
            if getattr(rating_vehicle, 'resale_value_5yr_estimate', None) is None:
                # Prefer a user-entered driveaway if available; fall back to stored value.
                state = (cv.state or 'NSW').upper()
                driveaway_cents = _get_state_cents(
                    getattr(rating_vehicle, 'driveaway_price_by_state', {}) or {},
                    state,
                )
                estimated = estimate_resale_value(
                    driveaway_cents=driveaway_cents,
                    year=getattr(rating_vehicle, 'year', 0) or 0,
                    powertrain_type=getattr(rating_vehicle, 'powertrain_type', None),
                    brand=getattr(rating_vehicle, 'brand', None) or getattr(rating_vehicle, 'make', None),
                )
                if estimated:
                    suggested_values['resale_value_5yr_estimate'] = estimated
                    badges['resale_value_5yr_estimate'] = {"source": "Default", "category": "vehicle_costs"}

        elif section == 'finance':
            # Conservative defaults for finance inputs.
            suggested_values['loan_term_months'] = 60
            suggested_values['interest_rate'] = 7.5

        return Response({
            "suggested_values": suggested_values,
            "badges": badges,
            "is_estimate": True,
            "disclaimer": "All figures are estimates only.",
        })


class CurrentVehicleSuggestionsView(views.APIView):
    """
    Type-ahead contract for current-vehicle lookup (Spec Type-Ahead §5-§7).

    - suggestions: ?q= query, >=3 chars, <=8 results, dedup preferring catalogue.
    - makes / models / years: cascade endpoints, include "Other / not listed".
    - Cached in Redis for 24 h; falls back to in-process cache if Redis is down.
    """
    permission_classes = [IsAuthenticated]

    MIN_QUERY_LEN = 3
    MAX_RESULTS = 8
    CACHE_TTL = 24 * 60 * 60  # 24 hours

    def _cache_key(self, prefix: str, *parts) -> str:
        safe = '_'.join(str(p).lower().replace(' ', '_') for p in parts if p is not None)
        return f'cv_typeahead_{prefix}_{safe}'[:250]

    def _other_option(self) -> dict:
        return {
            "id": "other",
            "name": "Other / not listed",
            "source": "other",
        }

    def _normalize_vehicle(self, v: Vehicle) -> dict:
        image_url = v.image_url or get_vehicle_image_url(
            v.brand,
            v.model,
            year=v.year,
            fcai_category=v.fcai_category,
            body_style=v.body_style,
            drive=v.drive,
            delay=0.05,
        )
        return {
            "id": str(v.id),
            "source": "carreb",
            "year": v.year,
            "make": v.brand,
            "model": v.model,
            "variant": v.variant,
            "body_style": v.body_style,
            "powertrain_type": v.powertrain_type,
            "image_url": image_url,
            "name": str(v),
        }

    def _normalize_gvg(self, r: VehicleIdentity) -> dict:
        image_url = r.image_url or get_vehicle_image_url(
            r.make,
            r.model,
            year=r.year,
            fcai_category=r.fcai_category,
            body_style=r.body_style,
            delay=0.05,
        )
        return {
            "id": str(r.id),
            "source": "gvg",
            "year": r.year,
            "make": r.make,
            "model": r.model,
            "variant": r.variant,
            "body_style": r.body_style,
            "powertrain_type": r.powertrain_type,
            "image_url": image_url,
            "name": f"{r.year} {r.make} {r.model} {r.variant}".strip(),
        }

    def _search_suggestions(self, query: str):
        query = (query or '').strip().lower()
        if len(query) < self.MIN_QUERY_LEN:
            return []

        cache_key = self._cache_key('suggestions', query)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        import re
        year_match = re.search(r'\b(19|20)\d{2}\b', query)
        year = int(year_match.group()) if year_match else None
        words = [w for w in re.sub(r'\b(19|20)\d{2}\b', ' ', query).split() if w]

        def text_filter(qs, brand_field='brand', model_field='model'):
            for w in words:
                qs = qs.filter(
                    models.Q(**{f'{brand_field}__icontains': w}) |
                    models.Q(**{f'{model_field}__icontains': w})
                )
            return qs

        results, seen = [], set()

        def identity_key(make, model_name, variant, yr):
            return ((make or '').casefold(), (model_name or '').casefold(),
                    (variant or '').casefold(), yr)

        # 1. Carreb catalogue (preferred on collision)
        carreb_qs = text_filter(Vehicle.objects.all(), brand_field='brand', model_field='model')
        if year:
            carreb_qs = carreb_qs.filter(year=year)
        for v in carreb_qs.order_by('brand', 'model', '-year')[:self.MAX_RESULTS]:
            seen.add(identity_key(v.brand, v.model, v.variant, v.year))
            results.append(self._normalize_vehicle(v))

        # 2. GVG records - trigram fuzzy fallback
        if len(results) < self.MAX_RESULTS:
            gvg_qs = VehicleIdentity.objects.all()
            remaining = self.MAX_RESULTS - len(results)

            if connection.vendor == 'postgresql':
                needle = (' '.join(([str(year)] if year else []) + words) or query).lower()
                gvg_qs = gvg_qs.annotate(
                    sim=TrigramSimilarity('search_text', needle)
                ).filter(sim__gt=0.05).order_by('-sim', '-year')
                if year:
                    gvg_qs = gvg_qs.filter(year=year)
            else:
                gvg_qs = text_filter(gvg_qs, brand_field='make', model_field='model')
                if year:
                    gvg_qs = gvg_qs.filter(year=year)
                gvg_qs = gvg_qs.order_by('make', 'model', '-year')

            for r in gvg_qs[:self.MAX_RESULTS * 2]:
                if len(results) >= self.MAX_RESULTS:
                    break
                key = identity_key(r.make, r.model, r.variant, r.year)
                if key in seen:
                    continue
                seen.add(key)
                results.append(self._normalize_gvg(r))

        cache.set(cache_key, results, self.CACHE_TTL)
        return results

    def get(self, request):
        endpoint = request.resolver_match.url_name if request.resolver_match else 'suggestions'

        if endpoint == 'current-vehicle-makes':
            return self._makes(request)
        if endpoint == 'current-vehicle-models':
            return self._models(request)
        if endpoint == 'current-vehicle-years':
            return self._years(request)
        return self._suggestions(request)

    def _suggestions(self, request):
        query = request.query_params.get('q', '').strip()
        results = self._search_suggestions(query)
        return Response({
            "q": query,
            "results": results,
            "not_found": not bool(results),
        })

    def _makes(self, request):
        cache_key = self._cache_key('makes')
        cached = cache.get(cache_key)
        if cached is None:
            carreb_makes = set(Vehicle.objects.values_list('brand', flat=True).distinct())
            gvg_makes = set(VehicleIdentity.objects.values_list('make', flat=True).distinct())
            cached = sorted({m for m in (carreb_makes | gvg_makes) if m})
            cache.set(cache_key, cached, self.CACHE_TTL)

        return Response({
            "results": [{"value": m, "label": m} for m in cached] + [self._other_option()],
        })

    def _models(self, request):
        make = (request.query_params.get('make') or '').strip()
        if not make:
            return Response({"results": [self._other_option()]})

        cache_key = self._cache_key('models', make)
        cached = cache.get(cache_key)
        if cached is None:
            q_make = make.casefold()
            carreb_models = set(
                Vehicle.objects.filter(brand__iexact=q_make).values_list('model', flat=True).distinct()
            )
            gvg_models = set(
                VehicleIdentity.objects.filter(make__iexact=q_make).values_list('model', flat=True).distinct()
            )
            cached = sorted({m for m in (carreb_models | gvg_models) if m})
            cache.set(cache_key, cached, self.CACHE_TTL)

        return Response({
            "make": make,
            "results": [{"value": m, "label": m} for m in cached] + [self._other_option()],
        })

    def _years(self, request):
        make = (request.query_params.get('make') or '').strip()
        model = (request.query_params.get('model') or '').strip()
        if not make or not model:
            return Response({"results": [self._other_option()]})

        cache_key = self._cache_key('years', make, model)
        cached = cache.get(cache_key)
        if cached is None:
            carreb_years = set(
                Vehicle.objects.filter(brand__iexact=make, model__iexact=model).values_list('year', flat=True).distinct()
            )
            gvg_years = set(
                VehicleIdentity.objects.filter(make__iexact=make, model__iexact=model).values_list('year', flat=True).distinct()
            )
            cached = sorted({int(y) for y in (carreb_years | gvg_years) if y}, reverse=True)
            cache.set(cache_key, cached, self.CACHE_TTL)

        return Response({
            "make": make,
            "model": model,
            "results": [{"value": y, "label": str(y)} for y in cached] + [self._other_option()],
        })

class GarageVehicleListView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        qs = GarageVehicle.objects.filter(user=request.user, status=GarageVehicleStatus.ACTIVE)
        
        state = getattr(request.user, 'priority_state', None)
        if not state:
            state = UserPriorityState.objects.create(user=request.user)
            
        cv_cost = None
        cv = getattr(request.user, 'current_vehicle', None)
        if cv:
            cv_resp = _build_calculated_vehicle_response(request.user, cv, state, is_current_vehicle=True)
            if cv_resp['engine_data']:
                cv_cost = cv_resp['engine_data'].get('total_annual_cost')
        
        results = []
        for gv in qs:
            results.append(_build_calculated_vehicle_response(request.user, gv, state, current_cost=cv_cost))
            
        # --- FILTERING LOGIC ---
        core_ratings_param = request.query_params.get('core_ratings')
        coo_5yrs_min_param = request.query_params.get('coo_5yrs_min')
        coo_5yrs_max_param = request.query_params.get('coo_5yrs_max')
        co2_emissions_param = request.query_params.get('co2_emissions')
        savings_param = request.query_params.get('savings')
        driveaway_min_param = request.query_params.get('driveaway_min')
        driveaway_max_param = request.query_params.get('driveaway_max')

        filtered_results = []
        for res in results:
            engine_data = res.get('engine_data')
            if not engine_data:
                # If there's no calculated data, we either include or exclude. 
                # Let's include by default unless specific filters are applied.
                if any([core_ratings_param, coo_5yrs_min_param, coo_5yrs_max_param, co2_emissions_param, savings_param, driveaway_min_param, driveaway_max_param]):
                    continue
                filtered_results.append(res)
                continue

            # 1. CORE Rating Filter
            if core_ratings_param:
                try:
                    valid_ratings = [int(r.strip()) for r in core_ratings_param.split(',')]
                    rounded_rating = int(round(engine_data.get('core_rating', 0)))
                    if rounded_rating not in valid_ratings:
                        continue
                except ValueError:
                    pass

            # 2. COO 5yrs Filter
            coo_5yrs = engine_data.get('total_annual_cost', 0) * 5
            if coo_5yrs_min_param:
                try:
                    if coo_5yrs < float(coo_5yrs_min_param): continue
                except ValueError: pass
            if coo_5yrs_max_param:
                try:
                    if coo_5yrs > float(coo_5yrs_max_param): continue
                except ValueError: pass

            # 3. CO2 Emissions Filter
            if co2_emissions_param:
                valid_buckets = [b.strip().lower() for b in co2_emissions_param.split(',')]
                tailpipe = engine_data.get('tailpipe_co2_g_per_km', 0)
                bucket = ''
                if tailpipe <= 50: bucket = 'very_low'
                elif 51 <= tailpipe <= 130: bucket = 'low'
                elif 131 <= tailpipe <= 180: bucket = 'medium'
                else: bucket = 'high'
                
                if bucket not in valid_buckets:
                    continue

            # 4. Savings (5yr) Filter
            if savings_param:
                valid_buckets = [b.strip().lower() for b in savings_param.split(',')]
                est_diff_obj = engine_data.get('est_cost_difference')
                bucket = ''
                if isinstance(est_diff_obj, dict) and est_diff_obj.get('direction') == 'saving':
                    bucket = est_diff_obj.get('savings_bucket') or ''

                if bucket not in valid_buckets:
                    continue

            # 5. Driveaway Price Filter
            driveaway_price = engine_data.get('annual_cost_breakdown', {}).get('driveaway_price', 0)
            if driveaway_min_param:
                try:
                    if driveaway_price < float(driveaway_min_param): continue
                except ValueError: pass
            if driveaway_max_param:
                try:
                    if driveaway_price > float(driveaway_max_param): continue
                except ValueError: pass

            filtered_results.append(res)
            
        # Use filtered results moving forward
        results = filtered_results

        # Optional sorting/filtering can be applied to `results` here
        sort_by = request.query_params.get('sort_by')
        if sort_by in ['core_rating', 'annual_cost', 'cost_difference', 'driveaway_price']:
            def sort_key(x):
                if not x.get('engine_data'): return 0
                if sort_by == 'cost_difference':
                    diff_obj = x['engine_data'].get('est_cost_difference')
                    if isinstance(diff_obj, dict):
                        return diff_obj.get('value_cents', 0) if diff_obj.get('direction') == 'saving' else -diff_obj.get('value_cents', 0)
                    return diff_obj or 0
                return x['engine_data'].get(sort_by) or 0
            results.sort(key=sort_key)
            
        return Response({
            "cap_counter": get_cap_counter(request.user),
            "vehicles": results
        })

    def post(self, request):
        serializer = GarageVehicleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        if not check_cap_limit(request.user):
            cap = get_cap_counter(request.user)
            return Response({
                "detail": f"Plan limit reached. You are on {cap['plan']} which allows {cap['limit']} vehicles.",
                "cap_counter": cap
            }, status=status.HTTP_403_FORBIDDEN)
            
        gv = GarageVehicle.objects.create(
            user=request.user,
            vehicle_catalogue_id=serializer.validated_data['vehicle_catalogue_id'],
            source=serializer.validated_data['source']
        )
        
        if getattr(request.user, 'analytics_consent', False):
            emit_analytics_event.delay(str(request.user.id), 'vehicle_added_to_garage', {})
            
        cache.delete(f"spotlights_{request.user.id}")
        return Response(GarageVehicleSerializer(gv).data, status=status.HTTP_201_CREATED)

class GarageVehicleDetailView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request, garage_vehicle_id):
        gv = get_object_or_404(GarageVehicle, id=garage_vehicle_id, user=request.user)
        state = getattr(request.user, 'priority_state', None)
        
        cv_cost = None
        cv = getattr(request.user, 'current_vehicle', None)
        if cv:
            cv_resp = _build_calculated_vehicle_response(request.user, cv, state, is_current_vehicle=True)
            if cv_resp['engine_data']:
                cv_cost = cv_resp['engine_data'].get('total_annual_cost')
                
        return Response(_build_calculated_vehicle_response(request.user, gv, state, current_cost=cv_cost))

class GarageVehicleOverrideView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def patch(self, request, garage_vehicle_id):
        gv = get_object_or_404(GarageVehicle, id=garage_vehicle_id, user=request.user)
        serializer = VehicleDetailOverrideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        VehicleOverride.objects.update_or_create(
            user=request.user,
            garage_vehicle=gv,
            field_name=serializer.validated_data['field_name'],
            defaults={'override_value': serializer.validated_data['override_value']}
        )
        
        if getattr(request.user, 'analytics_consent', False):
            emit_analytics_event.delay(str(request.user.id), 'vehicle_field_overridden', {'field_name': serializer.validated_data['field_name']})
            
        state = getattr(request.user, 'priority_state', None)
        return Response(_build_calculated_vehicle_response(request.user, gv, state))

    def delete(self, request, garage_vehicle_id, field_name):
        gv = get_object_or_404(GarageVehicle, id=garage_vehicle_id, user=request.user)
        deleted, _ = VehicleOverride.objects.filter(user=request.user, garage_vehicle=gv, field_name=field_name).delete()
        if not deleted:
            return Response({"detail": "Override not found"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            
        state = getattr(request.user, 'priority_state', None)
        return Response(_build_calculated_vehicle_response(request.user, gv, state))

class GarageVehicleArchiveView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, garage_vehicle_id):
        gv = get_object_or_404(GarageVehicle, id=garage_vehicle_id, user=request.user)
        gv.status = GarageVehicleStatus.ARCHIVED
        gv.archived_at = timezone.now()
        gv.save()
        
        if getattr(request.user, 'analytics_consent', False):
            emit_analytics_event.delay(str(request.user.id), 'vehicle_archived', {})
            
        cache.delete(f"spotlights_{request.user.id}")
        return Response({"status": "archived"})

class GarageVehicleUnarchiveView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, garage_vehicle_id):
        gv = get_object_or_404(GarageVehicle, id=garage_vehicle_id, user=request.user)
        if gv.status == GarageVehicleStatus.ACTIVE:
            return Response({"detail": "Already active"}, status=status.HTTP_400_BAD_REQUEST)
            
        if not check_cap_limit(request.user):
            cap = get_cap_counter(request.user)
            return Response({
                "detail": f"Plan limit reached. You are on {cap['plan']} which allows {cap['limit']} vehicles.",
                "cap_counter": cap
            }, status=status.HTTP_403_FORBIDDEN)
            
        gv.status = GarageVehicleStatus.ACTIVE
        gv.archived_at = None
        gv.save()
        
        if getattr(request.user, 'analytics_consent', False):
            emit_analytics_event.delay(str(request.user.id), 'vehicle_unarchived', {})
            
        cache.delete(f"spotlights_{request.user.id}")
        return Response({"status": "active"})

class GarageVehicleDeleteView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def delete(self, request, garage_vehicle_id):
        gv = get_object_or_404(GarageVehicle, id=garage_vehicle_id, user=request.user)
        if gv.status != GarageVehicleStatus.ARCHIVED:
            return Response({"detail": "Vehicle must be archived before deletion"}, status=status.HTTP_400_BAD_REQUEST)
            
        gv.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class ArchiveListView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        qs = GarageVehicle.objects.filter(user=request.user, status=GarageVehicleStatus.ARCHIVED)
        state = getattr(request.user, 'priority_state', None)
        
        results = []
        for gv in qs:
            results.append(_build_calculated_vehicle_response(request.user, gv, state))
            
        return Response(results)

class PriorityStateView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        state, _ = UserPriorityState.objects.get_or_create(user=request.user)
        return Response({
            "state": UserPriorityStateSerializer(state).data,
            "band_counts": {},
            "bands": _build_dial_bands(request.user, state),
        })

    def patch(self, request):
        state, _ = UserPriorityState.objects.get_or_create(user=request.user)
        
        mode = request.data.get('active_core_mode')
        if mode in ['cool_choice', 'true_value', 'full_picture'] and request.user.subscription_tier == SubscriptionTier.FREE:
            if getattr(request.user, 'analytics_consent', False):
                emit_analytics_event.delay(str(request.user.id), 'core_mode_upgrade_prompt_shown', {})
            return Response({"detail": "Premium mode requested on free tier"}, status=status.HTTP_403_FORBIDDEN)
            
        serializer = UserPriorityStateSerializer(state, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        if getattr(request.user, 'analytics_consent', False):
            emit_analytics_event.delay(str(request.user.id), 'core_dial_adjusted', {
                'priority_slider_position': serializer.validated_data.get('priority_slider_position'),
                'active_core_mode': serializer.validated_data.get('active_core_mode')
            })
            
        cache.delete(f"spotlights_{request.user.id}")

        # Build the band-level numbers the CORE Dial needs.
        dial_bands = _build_dial_bands(request.user, serializer.instance)
        band_counts = {b['slug'].replace('-', '_'): b['vehicle_count'] for b in dial_bands}

        response = {
            "state": serializer.data,
            "band_counts": band_counts,
            "bands": dial_bands,
        }
        cv = getattr(request.user, 'current_vehicle', None)
        if cv:
            cv_state = getattr(request.user, 'priority_state', serializer.instance)
            cv_resp = _build_calculated_vehicle_response(
                request.user, cv, cv_state, is_current_vehicle=True
            )
            response["current_vehicle"] = cv_resp

        return Response(response)

class CoreDialBandBreakdownView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request, band_slug):
        qs = GarageVehicle.objects.filter(user=request.user, status=GarageVehicleStatus.ACTIVE)
        state = getattr(request.user, 'priority_state', None)
        
        results = []
        for gv in qs:
            resp = _build_calculated_vehicle_response(request.user, gv, state)
            if resp['engine_data'] and resp['engine_data'].get('band_slug') == band_slug:
                results.append(resp)
                
        return Response(results)

class SavingsSummaryView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        cv = getattr(request.user, 'current_vehicle', None)
        if not cv:
            return Response({"message_variant": "no_current_vehicle"})
            
        state = getattr(request.user, 'priority_state', None)
        cv_resp = _build_calculated_vehicle_response(request.user, cv, state, is_current_vehicle=True)
        cv_cost = cv_resp['engine_data'].get('total_annual_cost') if cv_resp.get('engine_data') else None
        
        qs = GarageVehicle.objects.filter(user=request.user, status=GarageVehicleStatus.ACTIVE)
        if not qs.exists():
            return Response({"message_variant": "no_garage_vehicles", "current_vehicle_annual_cost": cv_cost})
            
        max_savings = -999999999
        best_gv = None
        
        for gv in qs:
            resp = _build_calculated_vehicle_response(request.user, gv, state, current_cost=cv_cost)
            diff_obj = resp['engine_data'].get('est_cost_difference') if resp.get('engine_data') else None
            diff_cents = None
            if isinstance(diff_obj, dict):
                if diff_obj.get('direction') == 'saving':
                    diff_cents = diff_obj.get('value_cents')
                elif diff_obj.get('direction') == 'more_expensive':
                    diff_cents = -diff_obj.get('value_cents')
                else:
                    diff_cents = 0
            else:
                diff_cents = diff_obj
                
            if diff_cents is not None and diff_cents > max_savings:
                max_savings = diff_cents
                best_gv = gv
                
        if max_savings > 0 and best_gv:
            return Response({
                "message_variant": "savings_available",
                "current_vehicle_annual_cost": cv_cost,
                "best_garage_vehicle_id": best_gv.id,
                "max_potential_annual_savings": max_savings
            })
        else:
            return Response({
                "message_variant": "no_savings_available",
                "current_vehicle_annual_cost": cv_cost
            })

class SpotlightsView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        if request.user.subscription_tier == SubscriptionTier.FREE:
            return Response({
                "error": "spotlights_locked",
                "message": "Spotlight badges are available on Car Buying Sprint and above.",
                "upgrade_required": True,
                "minimum_plan": "car_buying_sprint"
            }, status=status.HTTP_403_FORBIDDEN)
            
        cache_key = f"spotlights_{request.user.id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
            
        qs = GarageVehicle.objects.filter(
            user=request.user, 
            status=GarageVehicleStatus.ACTIVE
        ).select_related('vehicle_catalogue')
        
        user_state = getattr(request.user, 'priority_state', None)
        
        cv = getattr(request.user, 'current_vehicle', None)
        s = cv.state if cv and cv.state else 'NSW'
        
        # Calculate cv_cost once to pass along
        cv_cost = None
        if cv:
            cv_resp = _build_calculated_vehicle_response(request.user, cv, user_state, is_current_vehicle=True)
            cv_cost = cv_resp['engine_data'].get('total_annual_cost') if cv_resp.get('engine_data') else None
            
        results = calculate_spotlights(list(qs), user_state, s, cv_cost)
        
        cache.set(cache_key, results, 300)
        return Response(results)

class AISmartMatchView(views.APIView):
    permission_classes = [IsPaidMember]

    def post(self, request):
        serializer = AISmartMatchInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data['query']
        state = serializer.validated_data.get('state')
        if not state:
            cv = getattr(request.user, 'current_vehicle', None)
            state = cv.state if cv and getattr(cv, 'state', None) else 'NSW'

        user = request.user
        limit = user.get_match_limit()
        used = user.match_count_used
        
        # Step 1: Limit check
        if limit is not None and used >= limit:
            plan_name = dict(SubscriptionTier.choices).get(user.subscription_tier, "Free Starter")
            return Response({
                "error": "match_limit_reached",
                "match_count_used": used,
                "match_count_limit": limit,
                "plan": plan_name,
                "upgrade_message": "Upgrade to CORE Advantage for unlimited matches."
            }, status=status.HTTP_403_FORBIDDEN)
            
        # Step 2 & 3: AI extraction & Fallback
        ai_available, filters = extract_search_parameters(query)
        
        if not ai_available:
            AISmartMatchRequest.objects.create(
                user=user,
                raw_query=query,
                interpreted_filters=None,
                result_vehicle_ids=[],
                result_count=0,
                ai_service_available=False,
                match_count_at_time=used
            )
            if getattr(user, 'analytics_consent', False):
                emit_analytics_event.delay(str(user.id), 'ai_smart_match_fallback_shown', {})
                
            return Response({
                "results": [],
                "ai_service_available": False,
                "fallback_message": "AI matching is temporarily unavailable. Please use Smart Car Finder to find your vehicle."
            }, status=status.HTTP_200_OK)
            
        # Step 4: Query vehicles
        queryset = Vehicle.objects.all()
        
        def _ensure_list(val):
            if isinstance(val, str):
                return [val]
            return val if isinstance(val, list) else []

        if filters.get('powertrain_types'):
            pts = _ensure_list(filters['powertrain_types'])
            queryset = queryset.filter(powertrain_type__in=[p.lower() for p in pts])
            
        PRIMARY_USE_BODY_STYLES = {
            'city_commuter':  ["hatchback", "sedan"],
            'family_car':     ["suv", "wagon"],
            'mixed_use':      ["suv", "hatchback"],
            'long_distance':  ["suv", "sedan"],
            'work_vehicle':   ["ute", "van"],
        }
        
        if filters.get('body_styles'):
            bss = _ensure_list(filters['body_styles'])
            q = models.Q()
            for b in bss:
                q |= models.Q(body_style__icontains=b)
            queryset = queryset.filter(q)
        elif filters.get('primary_use'):
            use = filters['primary_use'].lower()
            bss = PRIMARY_USE_BODY_STYLES.get(use, [])
            if bss:
                q = models.Q()
                for b in bss:
                    q |= models.Q(body_style__icontains=b)
                queryset = queryset.filter(q)
                
        if filters.get('fcai_categories'):
            fcs = _ensure_list(filters['fcai_categories'])
            queryset = queryset.filter(fcai_category__in=fcs)
        if filters.get('num_seats_min'):
            queryset = queryset.filter(num_seats__gte=filters['num_seats_min'])
        if filters.get('ancap_rating_min'):
            queryset = queryset.filter(ancap_safety_rating__gte=filters['ancap_rating_min'])
            
        # Step 5: Score and sort
        user_state = getattr(user, 'priority_state', None)
        priority = user_state.priority_slider_position if user_state else 3
        mode = user_state.active_core_mode if user_state else CoreMode.PURE_COST
        
        cv = getattr(user, 'current_vehicle', None)
        cv_cost = None
        if cv and cv.vehicle_catalogue:
            cv_resp = calculate_core_rating(cv.vehicle_catalogue, state, priority, mode, {})
            cv_cost = cv_resp.get('total_annual_cost')
            
        all_vehicles = list(queryset)
        # Spec §4 mode letters: B=Pure Cost, E=COOL Choice, C=True Value, F=Full Picture
        mode_map = {
            'pure_cost': 'B',
            'cool_choice': 'E',
            'true_value': 'C',
            'full_picture': 'F'
        }
        mode_letter = mode_map.get(mode, 'B')
        
        cheapest_variants = {}
        for vehicle in all_vehicles:
            val = float('inf')
            try:
                state_data = vehicle.mode_data_by_state.get(state, {})
                if isinstance(state_data, dict):
                    mode_data = state_data.get(mode_letter, {})
                    if isinstance(mode_data, dict):
                        coo = mode_data.get("mode_5yr_coo")
                        if coo is not None:
                            val = float(coo)
            except (AttributeError, ValueError, TypeError):
                pass
            
            key = (vehicle.brand, vehicle.model, vehicle.year)
            if key not in cheapest_variants:
                cheapest_variants[key] = (val, vehicle)
            else:
                if val < cheapest_variants[key][0]:
                    cheapest_variants[key] = (val, vehicle)
                    
        unique_vehicles = [v for _, v in cheapest_variants.values()]

        scored_vehicles = []
        category_metrics_cache = {}
        for v in unique_vehicles:
            driveaway = v.driveaway_price_by_state.get(state)
            
            if filters.get('budget_max') and driveaway and driveaway > filters['budget_max'] * 100:
                continue
            if filters.get('budget_min') and driveaway and driveaway < filters['budget_min'] * 100:
                continue
                
            res = calculate_core_rating(
                vehicle=v,
                state=state,
                priority_slider=priority,
                core_mode=mode,
                user_inputs={},
                current_vehicle_annual_cost=cv_cost,
                category_metrics_cache=category_metrics_cache
            )
            rating = res.get('core_rating', 0)
            
            if filters.get('core_rating_min') and (not rating or rating < filters['core_rating_min']):
                continue
                
            reason = build_recommendation_reason(filters, v)
            
            diff_obj = res.get('est_cost_difference')
            if isinstance(diff_obj, dict):
                diff_val = diff_obj.get('value_cents')
                if diff_obj.get('direction') == 'more_expensive':
                    diff_val = -diff_val if diff_val else 0
                diff_display = diff_obj.get('value_display')
            else:
                diff_val = diff_obj
                if diff_val is not None:
                    diff_display = f"${abs(diff_val) // 100:,} {'less' if diff_val > 0 else 'more'}"
                else:
                    diff_display = None
                
            scored_vehicles.append({
                "vehicle_id": str(v.id),
                "make": v.brand,
                "model": v.model,
                "year": v.year,
                "variant": v.variant,
                "powertrain_type": v.powertrain_type,
                "core_rating": round(rating, 1) if rating else None,
                "band_name": res.get('band_name'),
                "total_annual_cost": res.get('total_annual_cost'),
                "total_annual_cost_display": f"${res.get('total_annual_cost', 0) // 100:,}",
                "est_cost_difference": diff_val,
                "est_cost_difference_display": diff_display,
                "co2_g_per_km": v.tailpipe_co2_g_per_km,
                "driveaway_price": driveaway,
                "driveaway_price_display": f"${driveaway // 100:,}" if driveaway else None,
                "recommendation_reason": reason,
                "is_estimate": True
            })
            
        scored_vehicles.sort(key=lambda x: x['core_rating'] or 0, reverse=True)
        scored_vehicles = scored_vehicles[:10]
        
        if not scored_vehicles:
            return Response({
                "results": [],
                "ai_service_available": True,
                "interpreted_filters": filters,
                "empty_message": "No vehicles matched your search. Try broadening your criteria or use Smart Car Finder.",
                "match_count_used": used,
                "match_count_limit": limit
            }, status=status.HTTP_200_OK)
            
        # Step 6: Increment counter
        user.match_count_used += 1
        user.save()
        
        # Step 7: Save request
        AISmartMatchRequest.objects.create(
            user=user,
            raw_query=query,
            interpreted_filters=filters,
            result_vehicle_ids=[v['vehicle_id'] for v in scored_vehicles],
            result_count=len(scored_vehicles),
            ai_service_available=True,
            match_count_at_time=used
        )
        
        if getattr(user, 'analytics_consent', False):
            emit_analytics_event.delay(str(user.id), 'ai_smart_match_performed', {
                'ai_service_available': True,
                'result_count': len(scored_vehicles)
            })

        # Step 8: Return
        return Response({
            "results": scored_vehicles,
            "match_count_used": user.match_count_used,
            "match_count_limit": limit,
            "ai_service_available": True,
            "meta": {
                "calculated_at": timezone.now().isoformat(),
                "is_estimate": True,
                "disclaimer": "All figures are estimates only. Actual costs will vary based on individual driving habits, insurer quotes, dealer pricing, and personal circumstances."
            }
        }, status=status.HTTP_200_OK)
from rest_framework import views, status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from apps.mygarage.models import RideRevealJob, RideRevealResult
from apps.mygarage.serializers import (
    RideRevealGenerateSerializer, 
    RideRevealPurchaseSerializer,
    RideRevealResultSerializer
)
from apps.mygarage.ridereveal_services import (
    get_ridereveal_credits,
    trigger_ridereveal_generation,
    create_stripe_payment_intent,
    process_stripe_webhook
)

class RideRevealCreditsView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = get_ridereveal_credits(request.user)
        return Response(data, status=status.HTTP_200_OK)

class RideRevealGenerateView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RideRevealGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        garage_vehicle_id = serializer.validated_data['garage_vehicle_id']
        custom_plate = serializer.validated_data.get('custom_plate')
        
        result = trigger_ridereveal_generation(request.user, garage_vehicle_id, custom_plate)
        
        status_code = result.pop('status_code')
        return Response(result, status=status_code)

class RideRevealJobView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        job = get_object_or_404(RideRevealJob, id=job_id, user=request.user)
        
        response_data = {
            "job_id": str(job.id),
            "status": job.status
        }
        
        if job.status == 'complete' and job.result:
            response_data['result'] = RideRevealResultSerializer(job.result).data
        elif job.status == 'failed':
            response_data['error_message'] = job.error_message
            response_data['credit_refunded'] = True
            
        return Response(response_data, status=status.HTTP_200_OK)

class RideRevealResultView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, garage_vehicle_id):
        try:
            result = RideRevealResult.objects.get(user=request.user, garage_vehicle_id=garage_vehicle_id)
            return Response(RideRevealResultSerializer(result).data, status=status.HTTP_200_OK)
        except RideRevealResult.DoesNotExist:
            return Response({"error": "not_found", "message": "No result found"}, status=status.HTTP_404_NOT_FOUND)

class RideRevealPurchaseView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RideRevealPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        purchase_type = serializer.validated_data['purchase_type']
        
        try:
            client_secret = create_stripe_payment_intent(request.user, purchase_type)
            return Response({"client_secret": client_secret}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class StripeWebhookView(views.APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
        
        success = process_stripe_webhook(payload, sig_header)
        
        if success:
            return Response(status=status.HTTP_200_OK)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)
