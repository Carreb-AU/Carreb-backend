import logging
import re

logger = logging.getLogger(__name__)

from rest_framework import views, status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
from django.db import models, connection
from django.contrib.postgres.search import TrigramSimilarity
from django.shortcuts import get_object_or_404
from apps.mygarage.models import (
    CurrentVehicle, GarageVehicle, GarageVehicleStatus, GarageVehicleSource,
    VehicleOverride, UserPriorityState, CoreMode, AISmartMatchRequest
)
from apps.vehicles.models import Vehicle, VehicleIdentity
from apps.vehicles.services.gvg_import import build_vehicle_like_from_gvg
from apps.vehicles.services.image_lookup import (
    get_used_vehicle_image_url,
    get_vehicle_image_url,
)
from apps.vehicles.services.vehicle_card import build_vehicle_card
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
from apps.vehicles.services.core_dial import (
    AU_STATES, cost_gvg_current_vehicle, resolve_garage_km, garage_km_copy_line)
from apps.vehicles.services.ai_vehicle_search import AIVehicleSearchError, search_ai_vehicles
from apps.vehicles.tasks import emit_analytics_event

def _get_overrides(user, current_vehicle=None, garage_vehicle=None):
    overrides = VehicleOverride.objects.filter(
        user=user, 
        current_vehicle=current_vehicle, 
        garage_vehicle=garage_vehicle
    )
    return {o.field_name: o.override_value for o in overrides}

def _category_avg_annual_cost(record, state) -> int:
    """Median catalogue COO p.a. (cents) for a class+state — the baseline
    the category-average cost difference compares against."""
    import statistics
    from apps.vehicles.models import CoreDialBatch, CoreDialRow
    batch = CoreDialBatch.objects.filter(is_current=True).first()
    if not batch:
        return 0
    values = [r.coo_pa_cents for r in CoreDialRow.objects.filter(
        batch=batch, state=(state or 'NSW').upper(),
        fcai_category__iexact=(record.fcai_category or ''))
        if r.coo_pa_cents]
    return int(statistics.median(values)) if values else 0


def _gvg_est_cost_diff(baseline_cents, total_cents, comparison_mode="current_vehicle"):
    """Shape-compatible est_cost_difference for non-catalogue (GVG/AI) vehicles.

    Mirrors the object calculate_core_rating builds for catalogue vehicles so
    the garage savings UI can consume both identically.
    """
    diff = baseline_cents - total_cents
    if comparison_mode == "current_vehicle":
        base_disp = f"Est. ${int(round(baseline_cents / 100)):,}/year"
    else:
        base_disp = f"Est. ${int(round(baseline_cents / 100)):,}/year\n      (category average)"
    if diff < 0:
        direction, val, bucket = "more_expensive", abs(diff), None
    elif diff > 0:
        direction, val = "saving", diff
        s5 = val * 5
        bucket = ("essentials_covered" if s5 < 250000
                  else "home_family" if s5 < 750000
                  else "savings_security" if s5 < 1250000
                  else "future_proof")
    else:
        direction, val, bucket = "same", 0, None
    s5 = val * 5
    return {
        "value_cents": val,
        "value_display": f"Est. ${int(round(val / 100)):,}/year",
        "direction": direction,
        "comparison_mode": comparison_mode,
        "baseline_cost": baseline_cents,
        "baseline_cost_display": base_disp,
        "est_5yr_savings": s5,
        "est_5yr_savings_display": f"Est. ${int(round(s5 / 100)):,} over 5 years",
        "savings_bucket": bucket,
    }


def _build_calculated_vehicle_response(user, vehicle_instance, priority_state, current_cost=None, is_current_vehicle=False):
    base_data = None
    overrides_qs = None

    if is_current_vehicle:
        base_data = CurrentVehicleSerializer(vehicle_instance).data
        overrides_qs = VehicleOverride.objects.filter(user=user, current_vehicle=vehicle_instance)
        # The CV card follows the user's selected CORE mode so the figures
        # are comparable with garage cards costed in that same mode (B-13:
        # cost differences must never mix modes). Per-mode costs are added
        # to engine_data below.
        mode = priority_state.active_core_mode if priority_state else CoreMode.PURE_COST
        priority = priority_state.priority_slider_position if priority_state else 3
        # State chain (spec section 8): saved priority state, else the current
        # car's state. If neither is set, fall back to NSW so a figure always
        # shows — the same fallback the garage-card path uses. Without it the
        # card rendered "—" forever when the frontend never prompted (and the
        # garage diff silently fell back to category-average comparisons).
        # state_defaulted tells the frontend it may still offer the picker.
        state = None
        if priority_state:
            state = priority_state.state
        if not state:
            state = vehicle_instance.state
        state = (state or '').upper() or None
        state_defaulted = state is None
        if state_defaulted:
            state = 'NSW'
        catalogue = vehicle_instance.vehicle_catalogue
        gvg_record = vehicle_instance.green_vehicle_guide_record
        ai_entry = getattr(vehicle_instance, 'ai_vehicle_entry', None)
    else:
        base_data = GarageVehicleSerializer(vehicle_instance).data
        overrides_qs = VehicleOverride.objects.filter(user=user, garage_vehicle=vehicle_instance)
        mode = priority_state.active_core_mode
        priority = priority_state.priority_slider_position
        # Assume state from current vehicle if exists, else default
        cv = getattr(user, 'current_vehicle', None)
        state = cv.state if cv and cv.state else 'NSW'
        state_defaulted = False
        catalogue = vehicle_instance.vehicle_catalogue
        gvg_record = vehicle_instance.green_vehicle_guide_record
        ai_entry = getattr(vehicle_instance, 'ai_vehicle_entry', None)

    if catalogue and base_data:
        base_data['source'] = 'carreb'

    # Build a vehicle-like object for rating. Prefer Carreb catalogue, then GVG record.
    rating_vehicle = catalogue
    card = None
    if not rating_vehicle and gvg_record:
        rating_vehicle = build_vehicle_like_from_gvg(gvg_record, state)
        base_data = base_data or {}
        base_data['gvg_record_id'] = str(gvg_record.id)
        base_data['source'] = 'gvg'
        card = build_vehicle_card(gvg_record, 'gvg', state=state)
    elif not rating_vehicle and ai_entry:
        # AI-searched car (missing from catalogue and GVG): specs from Grok,
        # costed like a GVG current car (class medians + own consumption).
        # Rows created before the estimate-filler existed are completed
        # lazily here (sheet defaults only — no AI tokens).
        if not ai_entry.ctp_by_state:
            from apps.vehicles.services.ai_entry_estimates import fill_ai_entry_estimates
            fill_ai_entry_estimates(ai_entry)
        rating_vehicle = ai_entry
        base_data = base_data or {}
        base_data['ai_vehicle_entry_id'] = str(ai_entry.id)
        base_data['source'] = 'ai'
        card = build_vehicle_card(ai_entry, 'ai', state=state)
    elif catalogue:
        card = build_vehicle_card(catalogue, 'carreb', state=state)

    # Merge the canonical full-field card into vehicle_data. Existing keys
    # (garage/current-vehicle ids, state, etc.) win; the card fills every
    # missing field with its database/default/AI value + field_sources map.
    if card is not None and base_data is not None:
        for key, value in card.items():
            if key == 'id':
                continue
            if key not in base_data or base_data.get(key) in (None, ''):
                base_data[key] = value
        if 'field_sources' not in base_data:
            base_data['field_sources'] = card.get('field_sources', {})
        # Backward-compat alias: cards expose the canonical name.
        if base_data.get('fuel_consumption_per_100km') in (None, '') \
                and card.get('fuel_consumption_combined_l_100km'):
            base_data['fuel_consumption_per_100km'] = \
                card['fuel_consumption_combined_l_100km']

        # Catalogue rows can lack AI-estimable specs too (ANCAP, tow,
        # engine size...). Same rule as search: never call Grok inline —
        # enqueue a fire-and-forget warmer and let the 30-day caches fill
        # in the card on a later view.
        warm_rec, warm_src = (catalogue, 'carreb') if catalogue \
            else (gvg_record, 'gvg') if gvg_record \
            else (ai_entry, 'ai') if ai_entry else (None, None)
        if warm_rec is not None \
                and not getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
            from apps.vehicles.services.vehicle_card import record_needs_warm
            from apps.vehicles.tasks import warm_vehicle_estimates_task
            _, needs = record_needs_warm(warm_rec, warm_src)
            if needs:
                warm_vehicle_estimates_task.delay(str(warm_rec.id), warm_src)

    user_inputs = {o.field_name: o.override_value for o in overrides_qs}

    # B-21: every card in the garage (current vehicle included) is costed at
    # the user's garage km — their Edit Vehicle km setting, else the ABS 2020
    # default. (The odometer derivation was retired 6-Nov-26 per Jock: it
    # assumed the car was bought new and overstated on used cars; odometer
    # and purchase date stay, optional, feeding resale only.) CORE ratings
    # and stars are untouched (km moves the dollars only, D29/D30).
    garage_km, garage_km_source = resolve_garage_km(priority_state)

    engine_data = None
    if rating_vehicle and state:
        if not catalogue:
            # Non-catalogue car (GVG or AI-searched): fixed class medians from
            # the Mode B rows plus the car's own consumption, costed at the
            # garage km (B-21). The user-set km arrives via
            # resolve_garage_km, which falls back to the ABS 2020 default —
            # never silently to the class benchmark.
            engine_data = cost_gvg_current_vehicle(
                rating_vehicle, state, annual_km=garage_km)
            if garage_km_source != 'default':
                engine_data['annual_km_basis'] = garage_km_source
            if current_cost is not None:
                engine_data['est_cost_difference'] = _gvg_est_cost_diff(current_cost, engine_data['total_annual_cost'])
            else:
                # Parity with catalogue vehicles: a GVG/AI current vehicle
                # compares against its category average (median catalogue
                # COO p.a. for the class in this state).
                engine_data['est_cost_difference'] = _gvg_est_cost_diff(
                    _category_avg_annual_cost(rating_vehicle, state),
                    engine_data['total_annual_cost'],
                    comparison_mode="category_avg")
        else:
            engine_data = calculate_core_rating(
                rating_vehicle,
                state,
                priority,
                mode,
                user_inputs,
                current_vehicle_annual_cost=current_cost,
                costed_km=garage_km
            )
            if is_current_vehicle:
                # Per-mode annual costs let the frontend switch CORE modes
                # without a refetch and let same-mode cost differences be
                # computed against the matching mode (B-13). Every mode is
                # costed at the same garage km (B-21).
                engine_data['mode_annual_costs'] = {}
                for m in CoreMode.values:
                    if m == mode:
                        engine_data['mode_annual_costs'][m] = \
                            engine_data.get('total_annual_cost')
                        continue
                    try:
                        res = calculate_core_rating(
                            rating_vehicle, state, priority, m, user_inputs,
                            costed_km=garage_km)
                        engine_data['mode_annual_costs'][m] = \
                            res.get('total_annual_cost')
                    except Exception:
                        engine_data['mode_annual_costs'][m] = None

    if engine_data:
        engine_data['costed_km'] = garage_km
        engine_data['costed_km_source'] = garage_km_source
        engine_data['costed_km_copy'] = garage_km_copy_line(garage_km, garage_km_source)
        engine_data['personalised_estimate'] = garage_km_source != 'default'

    return {
        "vehicle_data": base_data,
        "engine_data": engine_data,
        "overrides": user_inputs,
        "meta": {
            "calculated_at": timezone.now().isoformat(),
            "is_estimate": True,
            "state": state,
            "state_defaulted": state_defaulted,
            "costed_km": garage_km,
            "costed_km_source": garage_km_source,
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
        gvg_record_id = data.get('green_vehicle_guide_record_id')
        ai_entry_id = data.get('ai_vehicle_entry_id')
        exists_in_garage = False

        if vehicle_catalogue_id:
            exists_in_garage = GarageVehicle.objects.filter(
                user=request.user,
                vehicle_catalogue_id=vehicle_catalogue_id,
                status=GarageVehicleStatus.ACTIVE
            ).exists()
        elif gvg_record_id:
            exists_in_garage = GarageVehicle.objects.filter(
                user=request.user,
                green_vehicle_guide_record_id=gvg_record_id,
                status=GarageVehicleStatus.ACTIVE
            ).exists()
        elif ai_entry_id:
            exists_in_garage = GarageVehicle.objects.filter(
                user=request.user,
                ai_vehicle_entry_id=ai_entry_id,
                status=GarageVehicleStatus.ACTIVE
            ).exists()

        if (vehicle_catalogue_id or gvg_record_id or ai_entry_id) and not exists_in_garage:
            if not check_cap_limit(request.user):
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
                'ai_vehicle_entry_id': data.get('ai_vehicle_entry_id'),
                'manual_entry_data': data.get('manual_entry_data'),
                'purchase_date': data.get('purchase_date'),
                'licence_plate': data.get('licence_plate'),
                'odometer_reading': data.get('odometer_reading'),
                'state': data.get('state'),
            }
        )

        if data.get('ai_vehicle_entry_id'):
            from django.db.models import F as _F
            from apps.vehicles.models import AIVehicleEntry
            AIVehicleEntry.objects.filter(id=data['ai_vehicle_entry_id']).update(
                selected_count=_F('selected_count') + 1)
        
        if vehicle_catalogue_id and not exists_in_garage:
            GarageVehicle.objects.create(
                user=request.user,
                vehicle_catalogue_id=vehicle_catalogue_id,
                source=GarageVehicleSource.VEHICLE_LOOKUP
            )
            if getattr(request.user, 'analytics_consent', False):
                emit_analytics_event.delay(str(request.user.id), 'vehicle_added_to_garage', {})
        elif gvg_record_id and not exists_in_garage:
            GarageVehicle.objects.create(
                user=request.user,
                green_vehicle_guide_record_id=gvg_record_id,
                source=GarageVehicleSource.VEHICLE_LOOKUP
            )
            if getattr(request.user, 'analytics_consent', False):
                emit_analytics_event.delay(str(request.user.id), 'vehicle_added_to_garage', {})
        elif ai_entry_id and not exists_in_garage:
            GarageVehicle.objects.create(
                user=request.user,
                ai_vehicle_entry_id=ai_entry_id,
                source=GarageVehicleSource.VEHICLE_LOOKUP
            )
            if getattr(request.user, 'analytics_consent', False):
                emit_analytics_event.delay(str(request.user.id), 'vehicle_added_to_garage', {})
        
        state = getattr(request.user, 'priority_state', None)
        if not state:
            state = UserPriorityState.objects.create(user=request.user)

        # B-21: an explicit garage_km in the Edit Vehicle payload is the
        # user's one km setting (the only km source since the odometer
        # derivation was retired); explicit null reverts to the ABS default.
        if 'garage_km' in data:
            state.garage_km = data['garage_km']
            state.garage_km_user_set = data['garage_km'] is not None
            state.save(update_fields=['garage_km', 'garage_km_user_set', 'updated_at'])

        resp = _build_calculated_vehicle_response(request.user, cv, state, is_current_vehicle=True)
        cache.delete(f"spotlights_{request.user.id}")
        return Response(resp)

class AIVehicleSearchView(views.APIView):
    """
    POST /api/current-vehicle/ai-search/

    Explicit user action ("search with AI") for a current-vehicle search that
    found nothing in the catalogue or GVG dataset. Calls Grok once per
    distinct query; repeat searches are served from the AIVehicleEntry cache.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        query = (request.data.get('query') or '').strip()
        if len(query) < 3:
            return Response(
                {"detail": "Query too short — at least 3 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            entries, from_cache = search_ai_vehicles(query, user=request.user)
        except AIVehicleSearchError as exc:
            logger.info("AI vehicle search failed for %r: %s", query, exc)
            return Response(
                {"detail": str(exc), "ai_available": False, "results": []},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({
            "results": [self._serialize(e) for e in entries],
            "from_cache": from_cache,
            "ai_available": True,
        })

    @staticmethod
    def _serialize(e):
        card = build_vehicle_card(e, 'ai')
        card["search_count"] = e.search_count
        card["selected_count"] = e.selected_count
        return card


class CurrentVehicleSearchView(views.APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def _image_url_for(self, obj, source):
        """Kept for backward compatibility — delegates to the card helper."""
        card = build_vehicle_card(obj, source)
        return card.get('image_url')

    def _normalize_result(self, obj, source):
        """Canonical full-field card — identical shape for catalogue and GVG."""
        return build_vehicle_card(obj, source)

    def post(self, request):
        import re
        query = (request.data.get('query') or '').strip()
        if not query:
            return Response([])

        # Tokenise: a 4-digit token filters year; the rest match brand/model/variant.
        year_match = re.search(r'\b(19|20)\d{2}\b', query)
        year = int(year_match.group()) if year_match else None
        words = [w for w in re.sub(r'\b(19|20)\d{2}\b', ' ', query).split() if w]

        def text_filter(qs, brand_field='brand', model_field='model', variant_field='variant'):
            # Variant is searched too: Vehicle Lookup sends the picked trim
            # (e.g. "Bentayga Azure"), and without it one unknown word zeroes
            # the queryset and the whole response was replaced by AI guesses.
            for w in words:
                qs = qs.filter(
                    models.Q(**{f'{brand_field}__icontains': w}) |
                    models.Q(**{f'{model_field}__icontains': w}) |
                    models.Q(**{f'{variant_field}__icontains': w})
                )
            return qs

        results, seen = [], set()

        def identity_key(brand, model_name, variant, yr):
            return ((brand or '').casefold(), (model_name or '').casefold(),
                    (variant or '').casefold(), yr)

        records: list = []  # (record, source) pairs, warmed then carded

        # 1. Carreb catalogue (new vehicles; preferred on collision).
        # B-22: held (suppressed) listings are excluded from every catalogue
        # surface but stay selectable here — a held car can be a current
        # vehicle, just never a match/band/dial entry.
        carreb_qs = text_filter(Vehicle.objects.all(), brand_field='brand', model_field='model')
        if year:
            carreb_qs = carreb_qs.filter(year=year)
        for v in carreb_qs.order_by('brand', 'model', '-year')[:10]:
            seen.add(identity_key(v.brand, v.model, v.variant, v.year))
            records.append((v, 'carreb'))

        # 2. GVG records (older vehicles) - trigram fuzzy type-ahead
        if len(records) < 10:
            gvg_qs = VehicleIdentity.objects.all()
            if connection.vendor == 'postgresql':
                needle = (' '.join(([str(year)] if year else []) + words) or query).lower()
                gvg_qs = gvg_qs.annotate(
                    sim=TrigramSimilarity('search_text', needle)
                ).filter(sim__gt=0.05).order_by('-sim', '-year')
                if year:
                    # B-01: the MY label can differ from the release year
                    # (year=2024, MY=MY25) — match the MY-derived year in
                    # search_text as well as the release year itself.
                    gvg_qs = gvg_qs.filter(
                        models.Q(year=year)
                        | models.Q(search_text__icontains=str(year)))
            else:
                # Fallback for SQLite/development
                gvg_qs = text_filter(gvg_qs, brand_field='make', model_field='model')
                if year:
                    gvg_qs = gvg_qs.filter(
                        models.Q(year=year)
                        | models.Q(search_text__icontains=str(year)))
                gvg_qs = gvg_qs.order_by('make', 'model', '-year')

            for r in gvg_qs[:20]:
                if len(records) >= 10:
                    break
                key = identity_key(r.make, r.model, r.variant, r.year)
                if key in seen:
                    continue
                seen.add(key)
                records.append((r, 'gvg'))

        # GVG/AI results may lack AI-estimable spec fields (doors, tow,
        # ANCAP...). Never call Grok inline — a cold Grok call takes 10-30s
        # and would blow the response budget. Instead, enqueue fire-and-
        # forget warmers; the card reads whatever the 30-day caches hold
        # and fills in on the next view once the warmer lands.
        from apps.vehicles.services.vehicle_card import record_needs_warm
        from apps.vehicles.tasks import warm_vehicle_estimates_task
        for rec, src in records:
            if src not in ('gvg', 'ai', 'carreb'):
                continue
            _, needs = record_needs_warm(rec, src)
            if needs:
                warm_vehicle_estimates_task.delay(str(rec.id), src)

        results = [self._normalize_result(rec, src) for rec, src in records]

        # 3. Nothing in the DB *strictly* matches the query (e.g. an older
        #    car absent from both catalogue and GVG) -> bring in the AI
        #    (Grok) lookup, served from the AIVehicleEntry cache when possible.
        #    AI results are APPENDED to any DB rows, never a replacement:
        #    discarding real catalogue/GVG rows in favour of an AI guess
        #    produced wrong source/price/rating cards (e.g. a catalogue
        #    Bentley Bentayga shown as an un-rated $405K "AI estimate").
        if not self._strict_matches(results, words):
            ai_results = self._ai_fallback(query, year, words, request)
            if ai_results:
                for card in ai_results:
                    key = identity_key(
                        card.get('make'), card.get('model'),
                        card.get('variant'), card.get('year'),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(card)
                return Response(results)
            if not results:
                # DB found nothing at all and AI could not help either.
                return Response([])

        return Response(results)

    @staticmethod
    def _strict_matches(results, words):
        """True when some result matches every query word against its
        make/model/variant — i.e. the searched vehicle actually exists in
        the returned rows (loose trigram siblings like a RAV4 for a Camry
        query don't count)."""
        if not words:
            return bool(results)
        lowered = [w.casefold() for w in words]
        for r in results:
            hay = f"{r.get('make') or ''} {r.get('model') or ''} {r.get('variant') or ''}".casefold()
            if all(w in hay for w in lowered):
                return True
        return False

    def _ai_fallback(self, query, year, words, request):
        """Grok lookup for vehicles missing from the DB.

        Only spent on queries that look complete (make + model, >= 2 words)
        so type-ahead fragments don't burn tokens; repeat searches hit the
        AIVehicleEntry cache. Returns None when the fallback doesn't apply
        or the AI lookup fails — caller keeps the loose DB results.
        """
        if len(words) < 2:
            return None
        user = request.user if request.user.is_authenticated else None
        try:
            entries, _from_cache = search_ai_vehicles(query, user=user)
        except AIVehicleSearchError:
            return None

        out = []
        for e in entries:
            if year and e.year and abs(e.year - year) > 1:
                continue
            card = build_vehicle_card(e, 'ai')
            # Legacy aliases the current-vehicle picker already consumes.
            card["fuel_consumption_per_100km"] = card["fuel_consumption_combined_l_100km"]
            card["driveaway_price_estimate"] = e.driveaway_price_estimate
            out.append(card)
        return out or None

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
        # v3: B-22 — held listings included for current-vehicle selection;
        # bumps the namespace so pre-B-22 24 h cached results are not reused.
        return f'cv_typeahead_v3_{prefix}_{safe}'[:250]

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
            # B-22: held cars are selectable here; the FE shows the amber
            # notice when this is true.
            "is_suppressed": v.is_suppressed,
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

        # 1. Carreb catalogue (preferred on collision). B-22: held listings
        # stay selectable as a current vehicle (card flags is_suppressed).
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

        # Duplicate guard: re-adding a vehicle already in the garage returns
        # the existing active row instead of creating a second record.
        dup_filters = {'user': request.user, 'status': GarageVehicleStatus.ACTIVE}
        for fk in ('vehicle_catalogue_id', 'green_vehicle_guide_record_id',
                   'ai_vehicle_entry_id'):
            if serializer.validated_data.get(fk):
                dup_filters[fk] = serializer.validated_data[fk]
                break
        existing = GarageVehicle.objects.filter(**dup_filters).first()
        if existing:
            data = GarageVehicleSerializer(existing).data
            data['already_in_garage'] = True
            return Response(data, status=status.HTTP_200_OK)

        if not check_cap_limit(request.user):
            cap = get_cap_counter(request.user)
            return Response({
                "detail": f"Plan limit reached. You are on {cap['plan']} which allows {cap['limit']} vehicles.",
                "cap_counter": cap
            }, status=status.HTTP_403_FORBIDDEN)
            
        gv = GarageVehicle.objects.create(
            user=request.user,
            vehicle_catalogue_id=serializer.validated_data.get('vehicle_catalogue_id'),
            green_vehicle_guide_record_id=serializer.validated_data.get('green_vehicle_guide_record_id'),
            ai_vehicle_entry_id=serializer.validated_data.get('ai_vehicle_entry_id'),
            source=serializer.validated_data['source']
        )

        # First vehicle added to the garage becomes the current vehicle,
        # mirroring the reverse path (setting current vehicle creates a
        # garage row). Never overwrite an existing current vehicle.
        if not hasattr(request.user, 'current_vehicle'):
            CurrentVehicle.objects.create(
                user=request.user,
                vehicle_catalogue_id=gv.vehicle_catalogue_id,
                green_vehicle_guide_record_id=gv.green_vehicle_guide_record_id,
                ai_vehicle_entry_id=gv.ai_vehicle_entry_id,
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
        return Response({"state": UserPriorityStateSerializer(state).data})

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

        # Response is { state: {...} } only — the browser computes band counts
        # from the Dial dataset; the server never re-scores on a slider move.
        return Response({"state": serializer.data})

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

    PRIMARY_USE_BODY_STYLES = {
        'city_commuter':  ["hatchback", "sedan"],
        'family_car':     ["suv", "wagon"],
        'mixed_use':      ["suv", "hatchback"],
        'long_distance':  ["suv", "sedan"],
        'work_vehicle':   ["ute", "van"],
    }

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
            
        # Step 4: Query vehicles. DB-level filters are relaxed (least important
        # first) until at least MIN_RESULTS vehicles match, so the user never
        # gets 0-1 results from an over-strict query.
        MIN_RESULTS = 5

        queryset = Vehicle.objects.filter(is_suppressed=False)

        def _ensure_list(val):
            if isinstance(val, str):
                return [val]
            return val if isinstance(val, list) else []

        # Filters ordered LEAST important first — active.pop(0) drops the
        # least important when relaxing. Budget and core_rating are applied
        # later in Python (they depend on per-state vehicle data).
        filters_db = []
        if filters.get('ancap_rating_min'):
            filters_db.append(('ancap_rating_min',
                               models.Q(ancap_safety_rating__gte=filters['ancap_rating_min'])))
        body_q = models.Q()
        if filters.get('body_styles'):
            for b in _ensure_list(filters['body_styles']):
                body_q |= models.Q(body_style__icontains=b)
        elif filters.get('primary_use'):
            use = filters['primary_use'].lower()
            for b in self.PRIMARY_USE_BODY_STYLES.get(use, []):
                body_q |= models.Q(body_style__icontains=b)
        if body_q:
            filters_db.append(('body_styles', body_q))
        if filters.get('num_seats_min'):
            filters_db.append(('num_seats_min',
                               models.Q(num_seats__gte=filters['num_seats_min'])))
        if filters.get('powertrain_types'):
            pts = [p.lower() for p in _ensure_list(filters['powertrain_types'])]
            filters_db.append(('powertrain_types', models.Q(powertrain_type__in=pts)))
        if filters.get('fcai_categories'):
            fcs = _ensure_list(filters['fcai_categories'])
            filters_db.append(('fcai_categories', models.Q(fcai_category__in=fcs)))

        relaxed = []
        active = list(filters_db)
        while True:
            qs = queryset
            for _, q in active:
                qs = qs.filter(q)
            if qs.count() >= MIN_RESULTS or not active:
                break
            dropped, _ = active.pop(0)
            relaxed.append(dropped)

        # Step 5: Score and sort (two phases to bound calculate_core_rating calls)
        user_state = getattr(user, 'priority_state', None)
        priority = user_state.priority_slider_position if user_state else 3
        mode = user_state.active_core_mode if user_state else CoreMode.PURE_COST

        cv = getattr(user, 'current_vehicle', None)
        cv_cost = None
        if cv and cv.vehicle_catalogue:
            cv_resp = calculate_core_rating(cv.vehicle_catalogue, state, priority, mode, {})
            cv_cost = cv_resp.get('total_annual_cost')

        all_vehicles = list(qs)
        # Spec §4 mode letters: B=Pure Cost, E=COOL Choice, C=True Value, F=Full Picture
        mode_map = {
            'pure_cost': 'B',
            'cool_choice': 'E',
            'true_value': 'C',
            'full_picture': 'F'
        }
        mode_letter = mode_map.get(mode, 'B')

        def _mode_coo(vehicle):
            try:
                state_data = vehicle.mode_data_by_state.get(state, {})
                if isinstance(state_data, dict):
                    mode_data = state_data.get(mode_letter, {})
                    if isinstance(mode_data, dict):
                        coo = mode_data.get("mode_5yr_coo")
                        if coo is not None:
                            return float(coo)
            except (AttributeError, ValueError, TypeError):
                pass
            return float('inf')

        def _norm_name(s):
            return re.sub(r'[^a-z0-9]+', ' ', (s or '').casefold()).strip()

        make_n = _norm_name(filters.get('make'))
        model_n = _norm_name(filters.get('model'))

        def name_boost(vehicle):
            boost = 0
            if make_n and make_n in _norm_name(vehicle.brand):
                boost += 1
            if model_n and model_n in _norm_name(vehicle.model):
                boost += 2
            return boost

        category_metrics_cache = {}

        def build_results(effective):
            """Score and rank vehicles under the given effective filters.

            Returns the final result list (may be shorter than MIN_RESULTS).
            """
            def within_budget(vehicle):
                driveaway = vehicle.driveaway_price_by_state.get(state)
                # A budget constraint excludes vehicles with no price data for
                # this state (a car of unknown price can't satisfy a budget).
                if (effective.get('budget_min') or effective.get('budget_max')) \
                        and driveaway is None:
                    return False
                if effective.get('budget_max') and driveaway and \
                        driveaway > effective['budget_max'] * 100:
                    return False
                if effective.get('budget_min') and driveaway and \
                        driveaway < effective['budget_min'] * 100:
                    return False
                return True

            budget_min = effective.get('budget_min')
            budget_max = effective.get('budget_max')

            # Phase 1: one cheap representative (lowest 5yr COO variant) per
            # (brand, model) to order the model groups.
            reps = {}
            for vehicle in all_vehicles:
                if (budget_min or budget_max) and not within_budget(vehicle):
                    continue
                key = (vehicle.brand, vehicle.model)
                if key not in reps:
                    reps[key] = vehicle
                else:
                    if _mode_coo(vehicle) < _mode_coo(reps[key]):
                        reps[key] = vehicle

            scored_reps = []
            for key, vehicle in reps.items():
                res = calculate_core_rating(
                    vehicle=vehicle,
                    state=state,
                    priority_slider=priority,
                    core_mode=mode,
                    user_inputs={},
                    current_vehicle_annual_cost=cv_cost,
                    category_metrics_cache=category_metrics_cache
                )
                rating = res.get('core_rating', 0)
                if effective.get('core_rating_min') and (not rating or rating < effective['core_rating_min']):
                    continue
                scored_reps.append({
                    'key': key,
                    'vehicle': vehicle,
                    'rating': rating,
                    'annual_cost': res.get('total_annual_cost'),
                    'boost': name_boost(vehicle),
                })

            if not scored_reps:
                return []

            MAX_VARIANTS_PER_MODEL = 1
            MAX_RESULTS = 10
            scored_reps.sort(key=lambda r: (
                -r['boost'],
                -(r['rating'] or 0),
                r['annual_cost'] if r['annual_cost'] is not None else float('inf'),
            ))

            # Phase 2: fully score the variants of the top groups (enough groups to
            # fill MAX_RESULTS after per-model variant trim; name-matched groups
            # always included).
            selected = []
            filled = 0
            for rep in scored_reps:
                group_size = min(MAX_VARIANTS_PER_MODEL, sum(
                    1 for v in all_vehicles
                    if (v.brand, v.model) == rep['key'] and within_budget(v)))
                if rep['boost'] > 0 or filled < MAX_RESULTS:
                    selected.append((rep, group_size))
                    filled += group_size
                if filled >= MAX_RESULTS and len(selected) >= 2:
                    break

            selected_keys = {rep['key'] for rep, _ in selected}
            phase2 = [v for v in all_vehicles
                      if (v.brand, v.model) in selected_keys and within_budget(v)]

            entries = []
            for v in phase2:
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
                if effective.get('core_rating_min') and (not rating or rating < effective['core_rating_min']):
                    continue
                driveaway = v.driveaway_price_by_state.get(state)
                boost = name_boost(v)
                reason = build_recommendation_reason(effective, v)
                if boost >= 3:
                    reason = f"Your searched car — {v.brand} {v.model}. {reason}"

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

                entries.append({
                    "vehicle_id": str(v.id),
                    "make": v.brand,
                    "model": v.model,
                    "year": v.year,
                    "variant": v.variant,
                    "powertrain_type": v.powertrain_type,
                    "image_url": v.image_url or get_vehicle_image_url(
                        make=v.brand, model=v.model, year=v.year,
                        fcai_category=v.fcai_category, body_style=v.body_style,
                        drive=v.drive),
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
                    "is_estimate": True,
                    "model_group": f"{v.brand} {v.model} {v.year}",
                    "_boost": boost,
                    "_cost": res.get('total_annual_cost'),
                    "_rating": rating,
                    "_vehicle": v,
                })

            # Group variants: keep the best MAX_VARIANTS_PER_MODEL per model line,
            # groups ordered by name match, then rating, then cost (never alphabetical).
            groups = {}
            for e in entries:
                groups.setdefault((e['make'], e['model']), []).append(e)
            ordered = []
            for key in [rep['key'] for rep, _ in selected]:
                members = groups.get(key)
                if not members:
                    continue
                # One entry per model. Baseline: the cheapest variant — but a
                # better-rated trim within PRICE_TOLERANCE of the cheapest
                # price wins (a slightly pricier trim can be the smarter buy).
                # Unpriced variants only compete when no variant has a price.
                PRICE_TOLERANCE = 0.10
                priced = [e for e in members if e['driveaway_price'] is not None]
                if priced:
                    baseline = min(e['driveaway_price'] for e in priced)
                    within = [e for e in priced
                              if e['driveaway_price'] <= baseline * (1 + PRICE_TOLERANCE)]
                    best = max(within, key=lambda e: (
                        e['_rating'] or 0,
                        -(e['driveaway_price'] or 0),
                    ))
                else:
                    best = min(members, key=lambda e: (
                        -(e['_rating'] or 0),
                        e['_cost'] if e['_cost'] is not None else float('inf'),
                    ))
                ordered.append(best)

            out = []
            for e in ordered[:MAX_RESULTS]:
                v = e.pop('_vehicle')
                e.pop('_boost'), e.pop('_cost'), e.pop('_rating')
                # Fill the result out to the canonical card schema so AI Smart
                # Match rows carry the same complete field set as every other
                # search surface (existing match-specific keys win).
                card = build_vehicle_card(v, 'carreb', state=state)
                for k, val in card.items():
                    if k not in e or e.get(k) in (None, ''):
                        e[k] = val
                out.append(e)
            return out

        # Step 5 (cont.): build results, relaxing the Python-level filters
        # (core rating, then budget floor, then budget cap) if under MIN_RESULTS.
        effective = dict(filters)
        scored_vehicles = build_results(effective)
        for relaxed_key in ('core_rating_min', 'budget_min', 'budget_max'):
            if len(scored_vehicles) >= MIN_RESULTS:
                break
            if effective.pop(relaxed_key, None) is not None:
                relaxed.append(relaxed_key)
                scored_vehicles = build_results(effective)

        if not scored_vehicles:
            return Response({
                "results": [],
                "ai_service_available": True,
                "interpreted_filters": filters,
                "relaxed_filters": relaxed,
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
            "interpreted_filters": filters,
            "relaxed_filters": relaxed,
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
        favorite_color = serializer.validated_data.get('favorite_color')
        first_name = serializer.validated_data.get('first_name')

        result = trigger_ridereveal_generation(request.user, garage_vehicle_id, custom_plate, favorite_color, first_name)
        
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
