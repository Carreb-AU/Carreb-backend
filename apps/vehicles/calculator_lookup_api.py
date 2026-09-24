import re
import math
from typing import Optional, Tuple, Any

from rest_framework import views, status, serializers
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models.functions import Concat, Cast
from django.db.models import Value, CharField, Q

from apps.vehicles.models import (
    Vehicle,
    VehicleIdentity,
    ManualVehicleEnrichment,
    InsuranceCategoryBenchmark,
    InsuranceStateModifier,
    RegistrationFeeByState,
    RegistrationCategoryBenchmark,
    MaintenanceCategoryDefault,
    TyreCategoryDefault,
    FinanceDefault,
    NGAEmissionFactor,
    DepreciationLookup,
    VehicleCOOComponentBreakdown,
    PowertrainType,
)
from apps.vehicles.services.rating_engine import calculate_monthly_repayment


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

class VehicleFoundSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Vehicle record unique identifier (UUID or ID)")
    full_name = serializers.CharField(help_text="Full year make model variant title")
    brand = serializers.CharField(help_text="Manufacturer/Brand")
    model = serializers.CharField(help_text="Model name")
    variant = serializers.CharField(help_text="Trim or variant name", allow_blank=True)
    year = serializers.IntegerField(help_text="Model manufacturing year")


class TechnicalDetailsSerializer(serializers.Serializer):
    driveaway_price = serializers.FloatField(help_text="Estimated driveaway price in dollars")
    doors = serializers.IntegerField(help_text="Door count")
    seats = serializers.IntegerField(help_text="Seating capacity")
    drive_type = serializers.CharField(help_text="Drive type (Front, Rear, AWD, 4WD)")
    energy_type = serializers.CharField(help_text="Energy classification (diesel, petrol, electricity)")
    fuel_type = serializers.CharField(help_text="Fuel/powertrain type")
    fuel_efficiency = serializers.FloatField(help_text="Fuel efficiency (L/100km or kWh/100km)")
    battery_capacity_kwh = serializers.FloatField(allow_null=True, help_text="Battery capacity in kWh or null")
    range_km = serializers.FloatField(allow_null=True, help_text="Driving range in km or null")
    ancap_rating = serializers.IntegerField(help_text="ANCAP safety rating stars")


class VehicleCostsPaSerializer(serializers.Serializer):
    maintenance_cost = serializers.FloatField(help_text="Annual maintenance/servicing cost in dollars")
    insurance_cost = serializers.FloatField(help_text="Annual insurance premium in dollars")
    registration_cost = serializers.FloatField(help_text="Annual registration/CTP fee in dollars")
    tyre_cost = serializers.FloatField(help_text="Annualised tyre replacement cost in dollars")
    resale_value_est = serializers.FloatField(help_text="Estimated resale value after 5 years in dollars")
    depreciation_percentage = serializers.FloatField(help_text="Annual estimated depreciation percentage")


class FinanceSerializer(serializers.Serializer):
    loan_amount = serializers.FloatField(help_text="Financed loan principal in dollars")
    loan_term_months = serializers.IntegerField(help_text="Loan term in months")
    monthly_repayment = serializers.FloatField(help_text="Estimated monthly loan repayment in dollars")


class EnvironmentSerializer(serializers.Serializer):
    co2_emissions_kg_pa = serializers.IntegerField(help_text="Annual CO2 emissions in kg")
    off_grid_energy_pct = serializers.IntegerField(help_text="Percentage of off-grid/solar energy utilized")


class VehicleCalculatorLookupResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    query = serializers.CharField()
    vehicle_found = VehicleFoundSerializer()
    technical_details = TechnicalDetailsSerializer()
    vehicle_costs_pa = VehicleCostsPaSerializer()
    finance = FinanceSerializer()
    environment = EnvironmentSerializer()


# ---------------------------------------------------------------------------
# Database Lookup & Matching Helper
# ---------------------------------------------------------------------------

def find_vehicle_by_name(query: str) -> Optional[Tuple[str, Any]]:
    """
    Search `Vehicle` and `VehicleIdentity` by full name, variant, or fuzzy title match.
    Returns tuple of ('vehicle'|'identity', matched_instance) or None.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return None

    # Extract 4-digit year if present in query (e.g. 2025)
    year_match = re.search(r'\b(19\d\d|20\d\d)\b', cleaned_query)
    year = int(year_match.group(1)) if year_match else None

    # Build annotated Vehicle queryset with concatenated full title
    vehicle_qs = Vehicle.objects.annotate(
        full_title=Concat(
            Cast('year', CharField()), Value(' '),
            'brand', Value(' '),
            'model', Value(' '),
            'variant'
        ),
        title_no_year=Concat(
            'brand', Value(' '),
            'model', Value(' '),
            'variant'
        )
    )

    # 1. Trigram search on Vehicle
    # If a year was specified, first try filtering by that year for accuracy
    if year:
        year_filtered_qs = vehicle_qs.filter(year=year).annotate(
            similarity=TrigramSimilarity('full_title', cleaned_query)
        ).filter(similarity__gte=0.25).order_by('-similarity')
        best_v = year_filtered_qs.first()
        if best_v and best_v.similarity >= 0.30:
            return ('vehicle', best_v)

    # General trigram search across all years
    general_trigram_qs = vehicle_qs.annotate(
        similarity=TrigramSimilarity('full_title', cleaned_query)
    ).filter(similarity__gte=0.25).order_by('-similarity')
    best_v = general_trigram_qs.first()
    if best_v and best_v.similarity >= 0.35:
        return ('vehicle', best_v)

    # 2. Token / icontains matching fallback on Vehicle
    tokens = [t for t in re.split(r'[\s\-_]+', cleaned_query) if len(t) > 1 and not (t.isdigit() and len(t) == 4)]
    if tokens:
        q_tokens = Q()
        for t in tokens:
            q_tokens &= (Q(brand__icontains=t) | Q(model__icontains=t) | Q(variant__icontains=t))
        token_match = vehicle_qs.filter(q_tokens).order_by('-year').first()
        if token_match:
            return ('vehicle', token_match)

    # 3. Search VehicleIdentity (GVG / prior-year dataset)
    identity_qs = VehicleIdentity.objects.all()
    if year:
        identity_qs = identity_qs.filter(year=year)

    best_vi = identity_qs.annotate(
        similarity=TrigramSimilarity('search_text', cleaned_query.lower())
    ).filter(similarity__gte=0.25).order_by('-similarity').first()
    if best_vi and best_vi.similarity >= 0.30:
        return ('identity', best_vi)

    # Token fallback on VehicleIdentity
    if tokens:
        q_vi = Q()
        for t in tokens:
            q_vi &= (Q(make__icontains=t) | Q(model__icontains=t) | Q(variant__icontains=t))
        vi_token_match = VehicleIdentity.objects.filter(q_vi).order_by('-year').first()
        if vi_token_match:
            return ('identity', vi_token_match)

    return None


# ---------------------------------------------------------------------------
# Prefill Payload Builder
# ---------------------------------------------------------------------------

VALID_STATES = {'NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT'}


def _cents_to_dollars(cents_or_dollars: Optional[float]) -> float:
    """Normalize monetary values from internal cents/dollars to standard float dollars."""
    if cents_or_dollars is None:
        return 0.0
    val = float(cents_or_dollars)
    # If value is in cents (typically > 10,000 for car prices / costs)
    if val >= 10000.0:
        return round(val / 100.0, 2)
    return round(val, 2)


def build_prefill_payload(source_type: str, vehicle_obj: Any, query: str, state: str) -> dict:
    """
    Constructs the prefill dictionary matching all UI form fields.
    Cross-references Vehicle, VehicleIdentity, ManualVehicleEnrichment,
    VehicleCOOComponentBreakdown, and benchmark default tables.
    """
    clean_state = state.upper() if state and state.upper() in VALID_STATES else 'NSW'

    # 1. Identity & Naming
    if source_type == 'vehicle':
        v_id = str(vehicle_obj.id)
        brand = vehicle_obj.brand
        model = vehicle_obj.model
        variant = vehicle_obj.variant or ''
        year = vehicle_obj.year
        body_style = vehicle_obj.body_style or ''
        num_seats = vehicle_obj.num_seats or 5
        drive = vehicle_obj.drive or 'Front'
        powertrain = vehicle_obj.powertrain_type or PowertrainType.PETROL
        energy_norm = vehicle_obj.energy_norm or vehicle_obj.powertrain_type or 'petrol'
        fuel_consumption = vehicle_obj.fuel_consumption_per_100km
        elec_consumption = vehicle_obj.electricity_consumption_per_100km
        battery_kwh = vehicle_obj.battery_kwh
        wltp_range = vehicle_obj.wltp_range_km
        tailpipe_co2 = vehicle_obj.tailpipe_co2_g_per_km
        ancap_rating = vehicle_obj.ancap_safety_rating
        fcai_cat = vehicle_obj.fcai_category or 'Medium'
        fcai_broad = getattr(vehicle_obj, 'fcai_broad', '') or ''
        mode_data = vehicle_obj.mode_data_by_state.get(clean_state, {}) if isinstance(vehicle_obj.mode_data_by_state, dict) else {}

        # Driveaway price
        driveaway_cents = None
        if isinstance(vehicle_obj.driveaway_price_by_state, dict):
            driveaway_cents = vehicle_obj.driveaway_price_by_state.get(clean_state)
            if driveaway_cents is None:
                driveaway_cents = vehicle_obj.driveaway_price_by_state.get('NSW')
            if driveaway_cents is None and vehicle_obj.driveaway_price_by_state:
                driveaway_cents = next(iter(vehicle_obj.driveaway_price_by_state.values()), None)

        resale_value_cents = vehicle_obj.resale_value_5yr_estimate
        servicing_5yr_cents = vehicle_obj.servicing_5yr_estimate
        tyre_estimate_cents = vehicle_obj.tyre_replacement_estimate

    else:
        # VehicleIdentity
        v_id = str(vehicle_obj.id)
        brand = vehicle_obj.make
        model = vehicle_obj.model
        variant = vehicle_obj.variant or ''
        year = vehicle_obj.year
        body_style = vehicle_obj.body_style or ''
        num_seats = vehicle_obj.num_seats or 5
        drive = vehicle_obj.drive or 'Front'
        powertrain = vehicle_obj.powertrain_type or PowertrainType.PETROL
        energy_norm = vehicle_obj.fuel_type_raw or vehicle_obj.powertrain_type or 'petrol'
        fuel_consumption = vehicle_obj.fuel_consumption_combined_l_100km
        elec_consumption = (vehicle_obj.electricity_consumption_wh_per_km / 10.0) if vehicle_obj.electricity_consumption_wh_per_km else None
        battery_kwh = vehicle_obj.battery_kwh
        wltp_range = vehicle_obj.electric_range_km
        tailpipe_co2 = vehicle_obj.tailpipe_co2_g_per_km
        ancap_rating = None
        fcai_cat = vehicle_obj.fcai_category or 'Medium'
        fcai_broad = getattr(vehicle_obj, 'fcai_broad', '') or ''
        mode_data = {}
        driveaway_cents = vehicle_obj.driveaway_price_estimate
        resale_value_cents = vehicle_obj.resale_value_5yr_estimate
        servicing_5yr_cents = vehicle_obj.servicing_5yr_estimate
        tyre_estimate_cents = vehicle_obj.tyre_replacement_estimate

    # Check ManualVehicleEnrichment fallback for missing fields
    enrichment = None
    if source_type == 'identity':
        enrichment = getattr(vehicle_obj, 'manual_enrichment', None)
    else:
        enrichment = ManualVehicleEnrichment.objects.filter(
            record__make__iexact=brand,
            record__model__iexact=model,
            record__year=year
        ).first()

    if enrichment:
        if enrichment.ancap_safety_rating is not None:
            ancap_rating = enrichment.ancap_safety_rating
        if enrichment.driveaway_price_estimate is not None:
            driveaway_cents = enrichment.driveaway_price_estimate
        if enrichment.resale_value_5yr_estimate is not None:
            resale_value_cents = enrichment.resale_value_5yr_estimate

    full_name = f"{year} {brand} {model} {variant}".strip()

    # 2. Technical Details
    driveaway_price = _cents_to_dollars(driveaway_cents)
    # Default driveaway price if still 0.0 based on category benchmark / sensible baseline
    if driveaway_price <= 0.0:
        driveaway_price = 45000.0

    doors = 2 if any(term in body_style.lower() for term in ('coupe', 'convertible')) else 4
    seats = int(num_seats) if num_seats else 5
    drive_type = drive if drive else 'Front'

    is_bev = str(powertrain).lower() in (PowertrainType.BEV, 'electric', 'bev')
    is_phev = str(powertrain).lower() in (PowertrainType.PHEV, 'plug-in hybrid', 'phev')

    # Fuel efficiency
    if is_bev:
        if elec_consumption and elec_consumption > 0:
            fuel_efficiency = round(float(elec_consumption), 1)
        elif battery_kwh and wltp_range and wltp_range > 0:
            fuel_efficiency = round((float(battery_kwh) / float(wltp_range)) * 100.0, 1)
        else:
            fuel_efficiency = 16.5  # standard BEV kWh/100km default
    else:
        fuel_efficiency = round(float(fuel_consumption), 1) if fuel_consumption and fuel_consumption > 0 else 8.5

    battery_capacity_kwh = float(battery_kwh) if battery_kwh and battery_kwh > 0 else None
    range_km = float(wltp_range) if wltp_range and wltp_range > 0 else None
    resolved_ancap = int(ancap_rating) if ancap_rating is not None else 5

    # 3. Vehicle Costs (p.a.)
    # Check VehicleCOOComponentBreakdown for vehicle + state
    breakdown = VehicleCOOComponentBreakdown.get_breakdown_for_vehicle(brand, model, variant, year, clean_state)

    # Maintenance cost
    if breakdown and breakdown.maintenance_pa_cents > 0:
        maintenance_cost = _cents_to_dollars(breakdown.maintenance_pa_cents)
    elif servicing_5yr_cents and servicing_5yr_cents > 0:
        maintenance_cost = _cents_to_dollars(servicing_5yr_cents / 5.0)
    else:
        m_default = MaintenanceCategoryDefault.get_maintenance_for_category(fcai_cat)
        maintenance_cost = _cents_to_dollars(m_default.annual_avg_cents) if m_default else 350.0

    # Insurance cost
    if breakdown and breakdown.comprehensive_pa_cents > 0:
        insurance_cost = _cents_to_dollars(breakdown.comprehensive_pa_cents)
    else:
        ins_cents = InsuranceCategoryBenchmark.get_comprehensive_cents(fcai_cat, clean_state)
        insurance_cost = _cents_to_dollars(ins_cents)

    # Registration cost
    if breakdown and breakdown.registration_pa_cents > 0:
        registration_cost = _cents_to_dollars(breakdown.registration_pa_cents)
    else:
        rego_cents = RegistrationFeeByState.get_fee_cents(fcai_cat, clean_state)
        registration_cost = _cents_to_dollars(rego_cents)

    # Tyre cost
    if breakdown and breakdown.tyre_cost_pa_cents > 0:
        tyre_cost = _cents_to_dollars(breakdown.tyre_cost_pa_cents)
    elif tyre_estimate_cents and tyre_estimate_cents > 0:
        tyre_cost = _cents_to_dollars(tyre_estimate_cents / 5.0)
    else:
        t_default = TyreCategoryDefault.objects.filter(fcai_category__iexact=fcai_cat.strip()).first()
        if not t_default:
            t_default = TyreCategoryDefault.objects.filter(fcai_category__iexact='Medium').first()
        tyre_cost = _cents_to_dollars(t_default.annualised_cost_cents) if t_default else 216.0

    # Resale value & Depreciation
    retention_rate = DepreciationLookup.calculate_5yr_retention(fcai_cat, str(powertrain), brand)
    if resale_value_cents and resale_value_cents > 0:
        resale_value_est = _cents_to_dollars(resale_value_cents)
    elif mode_data.get('C', {}).get('resale_credit_pa'):
        resale_value_est = round(float(mode_data['C']['resale_credit_pa']) * 5.0, 2)
    else:
        resale_value_est = round(driveaway_price * retention_rate, 2)

    if driveaway_price > 0:
        # Annual depreciation percentage: ((driveaway - resale_5yr) / 5) / driveaway * 100
        depreciation_percentage = round(((driveaway_price - resale_value_est) / driveaway_price / 5.0) * 100.0, 2)
    else:
        depreciation_percentage = round(((1.0 - retention_rate) / 5.0) * 100.0, 2)

    # 4. Finance Defaults
    # Map broad category to FinanceDefault
    broad_key = fcai_broad
    if not broad_key:
        cat_lower = fcai_cat.lower()
        if 'suv' in cat_lower:
            broad_key = 'SUVs'
        elif any(w in cat_lower for w in ('commercial', 'van', 'ute', 'mover')):
            broad_key = 'Light Commercial'
        elif 'heavy' in cat_lower:
            broad_key = 'Heavy Commercial'
        else:
            broad_key = 'Passenger Cars'

    fin_default = FinanceDefault.objects.filter(fcai_category_broad__iexact=broad_key).first()
    if not fin_default:
        fin_default = FinanceDefault.objects.first()

    deposit_pct = fin_default.deposit_pct if fin_default else 10.0
    base_rate = fin_default.base_rate_pct if fin_default else 7.5
    if (is_bev or is_phev) and fin_default and fin_default.alt_fuel_modifier_pct:
        base_rate += fin_default.alt_fuel_modifier_pct

    loan_term_months = fin_default.term_months if fin_default else 60
    loan_amount = round(driveaway_price * (1.0 - (deposit_pct / 100.0)), 2)
    monthly_repayment = round(calculate_monthly_repayment(loan_amount, base_rate, loan_term_months), 2)

    # 5. Environment
    if mode_data.get('B', {}).get('annual_co2_kg') is not None:
        co2_emissions_kg_pa = int(round(float(mode_data['B']['annual_co2_kg'])))
    elif tailpipe_co2 and tailpipe_co2 > 0:
        annual_km = getattr(vehicle_obj, 'annual_km_default', 13300) or 13300
        co2_emissions_kg_pa = int(round((float(tailpipe_co2) * annual_km) / 1000.0))
    elif is_bev:
        # BEV upstream Scope 2 emissions based on NGA factor
        factor = NGAEmissionFactor.get_factor_for_state(clean_state)
        annual_km = getattr(vehicle_obj, 'annual_km_default', 13300) or 13300
        kwh_per_100 = fuel_efficiency if fuel_efficiency > 0 else 18.0
        co2_emissions_kg_pa = int(round((kwh_per_100 / 100.0) * annual_km * factor))
    else:
        co2_emissions_kg_pa = 0

    off_grid_energy_pct = 0

    return {
        "success": True,
        "query": query,
        "vehicle_found": {
            "id": v_id,
            "full_name": full_name,
            "brand": brand,
            "model": model,
            "variant": variant,
            "year": int(year),
        },
        "technical_details": {
            "driveaway_price": driveaway_price,
            "doors": doors,
            "seats": seats,
            "drive_type": drive_type,
            "energy_type": energy_norm,
            "fuel_type": str(powertrain),
            "fuel_efficiency": fuel_efficiency,
            "battery_capacity_kwh": battery_capacity_kwh,
            "range_km": range_km,
            "ancap_rating": resolved_ancap,
        },
        "vehicle_costs_pa": {
            "maintenance_cost": maintenance_cost,
            "insurance_cost": insurance_cost,
            "registration_cost": registration_cost,
            "tyre_cost": tyre_cost,
            "resale_value_est": resale_value_est,
            "depreciation_percentage": depreciation_percentage,
        },
        "finance": {
            "loan_amount": loan_amount,
            "loan_term_months": loan_term_months,
            "monthly_repayment": monthly_repayment,
        },
        "environment": {
            "co2_emissions_kg_pa": co2_emissions_kg_pa,
            "off_grid_energy_pct": off_grid_energy_pct,
        }
    }


# ---------------------------------------------------------------------------
# API View
# ---------------------------------------------------------------------------

class VehicleCalculatorLookupAPIView(views.APIView):
    """
    Read-only Vehicle Name Lookup & Auto-Fill API for Calculator UI.
    Endpoint: GET /api/v1/vehicles/lookup/?name=<vehicle_name>&state=<state>
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        name_query = request.query_params.get('name', '').strip()
        state = request.query_params.get('state', 'NSW').strip()

        if not name_query:
            return Response(
                {
                    "success": False,
                    "error": "Query parameter 'name' is required (e.g. ?name=2025 LDV V80 High Roof&state=NSW)."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        match_result = find_vehicle_by_name(name_query)
        if not match_result:
            return Response(
                {
                    "success": False,
                    "query": name_query,
                    "message": f"No vehicle found matching query '{name_query}'."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        source_type, vehicle_obj = match_result
        payload = build_prefill_payload(source_type, vehicle_obj, name_query, state)

        # Validate with response serializer
        serializer = VehicleCalculatorLookupResponseSerializer(data=payload)
        if serializer.is_valid():
            return Response(serializer.data, status=status.HTTP_200_OK)

        # Fallback to direct payload if serializer has formatting warnings
        return Response(payload, status=status.HTTP_200_OK)
