from rest_framework import views, status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db import models
from django.shortcuts import get_object_or_404
from apps.mygarage.models import (
    CurrentVehicle, GarageVehicle, GarageVehicleStatus, GarageVehicleSource,
    VehicleOverride, UserPriorityState, CoreMode, AISmartMatchRequest
)
from apps.vehicles.models import Vehicle
from apps.users.models import SubscriptionTier
from apps.mygarage.serializers import (
    CurrentVehicleSerializer, GarageVehicleSerializer,
    UserPriorityStateSerializer, CurrentVehicleCreateSerializer,
    GarageVehicleCreateSerializer, VehicleDetailOverrideSerializer,
    AISmartMatchInputSerializer
)
from apps.mygarage.services import check_cap_limit, get_cap_counter, calculate_spotlights
from apps.mygarage.ai_service import extract_search_parameters, build_recommendation_reason
from apps.vehicles.services.rating_engine import calculate_core_rating
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
    else:
        base_data = GarageVehicleSerializer(vehicle_instance).data
        overrides_qs = VehicleOverride.objects.filter(user=user, garage_vehicle=vehicle_instance)
        mode = priority_state.active_core_mode
        priority = priority_state.priority_slider_position
        # Assume state from current vehicle if exists, else default
        cv = getattr(user, 'current_vehicle', None)
        state = cv.state if cv and cv.state else 'NSW'
        catalogue = vehicle_instance.vehicle_catalogue

    user_inputs = {o.field_name: o.override_value for o in overrides_qs}
    
    engine_data = None
    if catalogue:
        engine_data = calculate_core_rating(
            catalogue, 
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
        return Response(resp)

class CurrentVehicleSearchView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        query = request.data.get('query', '').lower()
        if not query:
            return Response([])
        # Basic text search on brand, model, year
        qs = Vehicle.objects.filter(
            models.Q(brand__icontains=query) | 
            models.Q(model__icontains=query) |
            models.Q(year__icontains=query)
        )[:10]
        return Response([{"id": v.id, "name": str(v)} for v in qs])

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
        return Response(_build_calculated_vehicle_response(request.user, cv, state, is_current_vehicle=True))

class CurrentVehicleAutoFillView(views.APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        section = request.data.get('section')
        if section not in ['technical_details', 'vehicle_costs', 'finance']:
            return Response({"detail": "Invalid section"}, status=status.HTTP_400_BAD_REQUEST)
        # Placeholder for AI logic
        return Response({
            "suggested_values": {
                "annual_km": 15000,
                "insurance_override": 1200
            }
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
            
        # Optional sorting/filtering can be applied to `results` here
        sort_by = request.query_params.get('sort_by')
        if sort_by in ['core_rating', 'annual_cost', 'cost_difference', 'driveaway_price']:
            # Example sort implementation
            results.sort(key=lambda x: x['engine_data'].get(sort_by) if x['engine_data'] else 0)
            
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
        return Response(UserPriorityStateSerializer(state).data)
        
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
            
        # recalculate band counts
        qs = GarageVehicle.objects.filter(user=request.user, status=GarageVehicleStatus.ACTIVE)
        bands = {'net_zero_ninja': 0, 'smart_move': 0, 'steady_cruiser': 0, 'the_detour': 0, 'captain_carbon': 0}
        
        cv = getattr(request.user, 'current_vehicle', None)
        user_state = getattr(cv, 'state', 'NSW') if cv else 'NSW'
        
        for gv in qs:
            resp = _build_calculated_vehicle_response(request.user, gv, serializer.instance)
            b = resp['engine_data'].get('band_slug') if resp.get('engine_data') else None
            if b:
                b_key = b.replace('-', '_')
                if b_key in bands:
                    bands[b_key] += 1
                    
        return Response({"state": serializer.data, "band_counts": bands})

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
            diff = resp['engine_data'].get('est_cost_difference') if resp.get('engine_data') else None
            if diff and diff > max_savings:
                max_savings = diff
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
            return Response({"detail": "Spotlights locked on free tier"}, status=status.HTTP_403_FORBIDDEN)
            
        qs = GarageVehicle.objects.filter(user=request.user, status=GarageVehicleStatus.ACTIVE)
        user_state = getattr(request.user, 'priority_state', None)
        
        cv = getattr(request.user, 'current_vehicle', None)
        s = getattr(cv, 'state', 'NSW') if cv else 'NSW'
        
        # Calculate cv_cost once to pass along
        cv_cost = None
        if cv:
            cv_resp = _build_calculated_vehicle_response(request.user, cv, user_state, is_current_vehicle=True)
            cv_cost = cv_resp['engine_data'].get('total_annual_cost') if cv_resp.get('engine_data') else None
            
        results = {}
        for gv in qs:
            badges = calculate_spotlights(gv, user_state, s, cv_cost, list(qs))
            results[str(gv.id)] = badges
            
        return Response(results)

class AISmartMatchView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AISmartMatchInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data['query']
        state = serializer.validated_data['state']

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
        
        if filters.get('powertrain_types'):
            queryset = queryset.filter(powertrain_type__in=[p.lower() for p in filters['powertrain_types']])
        if filters.get('body_styles'):
            queryset = queryset.filter(body_style__in=[b.lower() for b in filters['body_styles']])
        if filters.get('fcai_categories'):
            queryset = queryset.filter(fcai_category__in=filters['fcai_categories'])
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

        scored_vehicles = []
        for v in queryset:
            driveaway = v.driveaway_price_by_state.get(state)
            
            if filters.get('budget_max') and driveaway and driveaway > filters['budget_max'] * 100:
                continue
            if filters.get('budget_min') and driveaway and driveaway < filters['budget_min'] * 100:
                continue
                
            res = calculate_core_rating(v, state, priority, mode, {}, current_vehicle_annual_cost=cv_cost)
            rating = res.get('core_rating', 0)
            
            if filters.get('core_rating_min') and (not rating or rating < filters['core_rating_min']):
                continue
                
            reason = build_recommendation_reason(filters, v)
            
            diff = res.get('est_cost_difference')
            if diff is not None:
                diff_display = f"${abs(diff) // 100:,} {'less' if diff > 0 else 'more'}"
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
                "est_cost_difference": diff,
                "est_cost_difference_display": diff_display,
                "co2_g_per_km": v.tailpipe_co2_g_per_km,
                "driveaway_price": driveaway,
                "driveaway_price_display": f"${driveaway // 100:,}" if driveaway else None,
                "recommendation_reason": reason,
                "is_estimate": True
            })
            
        scored_vehicles.sort(key=lambda x: x['core_rating'] or 0, reverse=True)
        
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
