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
    deposit_pct = serializers.FloatField(help_text="Deposit as % of driveaway (default from FinanceDefaults, typically 10)")
    deposit_amount = serializers.FloatField(help_text="Deposit in dollars (driveaway × deposit_pct)")
    loan_amount = serializers.FloatField(help_text="Financed loan principal in dollars (driveaway − deposit)")
    loan_term_months = serializers.IntegerField(help_text="Loan term in months (default from FinanceDefaults, typically 60)")
    interest_rate_pct = serializers.FloatField(help_text="Interest rate % p.a. before fees (FinanceDefaults base rate + alt-fuel modifier for BEV/PHEV)")
    balloon_pct = serializers.FloatField(help_text="End-of-term balloon/residual as % of loan (default from FinanceDefaults)")
    balloon_amount = serializers.FloatField(help_text="Balloon amount in dollars")
    monthly_repayment = serializers.FloatField(help_text="Calculated monthly P&I repayment in dollars (read-only; fees excluded)")
    monthly_repayment_display = serializers.CharField(help_text="Formatted monthly repayment, e.g. '$771'")
    finance_cost_pa = serializers.FloatField(help_text="Calculated yearly interest + fees in dollars (for the 'Finance – $X' header)")
    finance_cost_pa_display = serializers.CharField(help_text="Formatted yearly interest + fees, e.g. '$1,987'")
    estab_fee = serializers.FloatField(help_text="One-off establishment fee in dollars")
    admin_fee_monthly = serializers.FloatField(help_text="Monthly admin fee in dollars")


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

def _model_tokens(model: str):
    return [t for t in re.split(r'[^a-z0-9]+', (model or '').casefold()) if t]


def _score_candidate(make, model, variant, year, tokens):
    """
    Score a candidate against query tokens and report whether the query fully
    identifies the model.

    Returns (coverage, score, brand_hit, model_hits). Coverage is 1 when every
    word of the model name appears in the query tokens — e.g. "mazda 3" fully
    identifies model "3" but NOT "CX-3" (the model also contains "cx"). This
    stops near-miss models from outranking an exact model match on a year
    coincidence: without it, "2015 mazda 3 neo" would rank a 2015 CX-3 (year
    exact) above the 2014 Mazda 3, and "2025 mazda cx-5 maxx" would fall
    through to a CX-3.
    """
    make = (make or '').casefold()
    model = (model or '').casefold()
    variant = (variant or '').casefold()
    compact_model = re.sub(r'[^a-z0-9]', '', model)

    score = 0
    brand_hit = False
    model_hits = []
    for t in tokens:
        if t in model or (len(t) >= 3 and compact_model and t in compact_model):
            score += 4
            model_hits.append(t)
        elif t in variant:
            score += 3
        elif t in make:
            score += 2
            brand_hit = True

    coverage = (
        all(t in tokens for t in _model_tokens(model))
        or any(compact_model and compact_model in t for t in tokens)
    )
    return (1 if coverage else 0), score, brand_hit, model_hits


def _rank_key(make, model, variant, year, tokens, query_year):
    coverage, score, _, _ = _score_candidate(make, model, variant, year, tokens)
    yr = year or 0
    year_exact = bool(query_year and yr == query_year)
    year_diff = abs(yr - query_year) if (query_year and yr) else 0
    return (coverage, score, year_exact, -year_diff, yr)


def _best_scored(queryset, fields, tokens, query_year):
    """
    Iterate DB-prefiltered candidates (any token hits make/brand, model or
    variant), keep eligible ones, and return the best-ranked instance.
    Eligibility = the model is fully covered by the query tokens AND the model
    is genuinely identified: either the brand matched, or the model match is
    distinctive (two+ tokens, or a single token of 3+ chars). This rejects
    one-digit coincidences like "3" hitting Smart "#3", while still accepting
    brandless queries such as "corolla" or "land cruiser".
    `fields` maps (brand_field, model_field, variant_field, year_field).
    """
    brand_f, model_f, variant_f, year_f = fields
    best_obj, best_key = None, None
    for row in queryset:
        fields_vals = (getattr(row, brand_f), getattr(row, model_f),
                       getattr(row, variant_f), getattr(row, year_f))
        coverage, score, brand_hit, model_hits = _score_candidate(*fields_vals, tokens)
        distinctive = len(model_hits) >= 2 or any(len(t) >= 3 for t in model_hits)
        if not (coverage and score >= 4 and (brand_hit or distinctive)):
            continue
        key = _rank_key(*fields_vals, tokens, query_year)
        if best_key is None or key > best_key:
            best_obj, best_key = row, key
    return best_obj


def find_vehicle_by_name(query: str) -> Optional[Tuple[str, Any]]:
    """
    Search `Vehicle` and `VehicleIdentity` by full name, variant, or fuzzy title match.
    Returns tuple of ('vehicle'|'identity', matched_instance) or None.

    Matching order:
      1. Scored token match on the catalogue: a candidate is eligible only when
         the query tokens fully cover its model name AND hit the model — then
         rank by coverage, score, exact year, year proximity, newest year.
         ("2025 Mazda CX-5 Maxx" resolves to the 2026 CX-5 rather than a 2025
         CX-3, because "Maxx" only exists on the old CX-3 generation.)
      2. Same scored match on VehicleIdentity (GVG dataset) — covers older /
         discontinued cars absent from the catalogue, with nearest-year
         preference ("2015 Mazda 3 Neo" -> 2014 Mazda 3 when 2015 is missing).
      3. Trigram fuzzy fallback (catches typos like "toytota corola").
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return None

    # Extract 4-digit year if present in query (e.g. 2025)
    year_match = re.search(r'\b(19\d\d|20\d\d)\b', cleaned_query)
    year = int(year_match.group(1)) if year_match else None

    # Alphanumeric tokens; keep short digit tokens (model numbers like "3" or
    # the "5" in "CX-5") — dropping them is what made CX-5 match a CX-3.
    tokens = [t for t in re.split(r'[^a-z0-9]+', cleaned_query.casefold())
              if t and not (t.isdigit() and len(t) == 4)]

    if tokens:
        # DB prefilter: at least one token must hit brand/make, model or variant.
        veh_q = Q()
        id_q = Q()
        for t in tokens:
            veh_q |= (Q(brand__icontains=t) | Q(model__icontains=t) | Q(variant__icontains=t))
            id_q |= (Q(make__icontains=t) | Q(model__icontains=t) | Q(variant__icontains=t))

        best_v = _best_scored(
            Vehicle.objects.filter(veh_q).only('brand', 'model', 'variant', 'year'),
            ('brand', 'model', 'variant', 'year'), tokens, year)
        if best_v:
            return ('vehicle', best_v)

        best_i = _best_scored(
            VehicleIdentity.objects.filter(id_q).only('make', 'model', 'variant', 'year'),
            ('make', 'model', 'variant', 'year'), tokens, year)
        if best_i:
            return ('identity', best_i)

    # 3. Trigram fuzzy fallback (typo tolerance) — vehicle first, then identity
    vehicle_qs = Vehicle.objects.annotate(
        full_title=Concat(
            Cast('year', CharField()), Value(' '),
            'brand', Value(' '),
            'model', Value(' '),
            'variant'
        ),
    )

    if year:
        best_v = vehicle_qs.filter(year=year).annotate(
            similarity=TrigramSimilarity('full_title', cleaned_query)
        ).filter(similarity__gte=0.25).order_by('-similarity').first()
        if best_v and best_v.similarity >= 0.30:
            return ('vehicle', best_v)

    best_v = vehicle_qs.annotate(
        similarity=TrigramSimilarity('full_title', cleaned_query)
    ).filter(similarity__gte=0.25).order_by('-similarity').first()
    if best_v and best_v.similarity >= 0.35:
        return ('vehicle', best_v)

    identity_qs = VehicleIdentity.objects.all()
    if year:
        identity_qs = identity_qs.filter(year=year)
    best_vi = identity_qs.annotate(
        similarity=TrigramSimilarity('search_text', cleaned_query.lower())
    ).filter(similarity__gte=0.25).order_by('-similarity').first()
    if best_vi and best_vi.similarity >= 0.30:
        return ('identity', best_vi)

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
    balloon_pct = fin_default.balloon_pct if fin_default else 0.0

    deposit_amount = round(driveaway_price * deposit_pct / 100.0, 2)
    loan_amount = round(driveaway_price - deposit_amount, 2)
    balloon_amount = round(loan_amount * balloon_pct / 100.0, 2)
    monthly_repayment = round(
        calculate_monthly_repayment(loan_amount, base_rate, loan_term_months, balloon_amount), 2)

    # Yearly interest + fees for the "Finance – $X" header. Fees: monthly
    # admin fee across the term + one-off establishment fee (BEV rate for BEVs).
    estab_fee_cents = (fin_default.estab_fee_bev if is_bev else fin_default.estab_fee_default) \
        if fin_default else 40000
    admin_fee_cents = fin_default.admin_fee_monthly if fin_default else 1000
    years = loan_term_months / 12.0
    interest_total = monthly_repayment * loan_term_months + balloon_amount - loan_amount
    finance_cost_pa = round(
        interest_total / years + (admin_fee_cents * loan_term_months + estab_fee_cents) / 100.0 / years, 2)

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
            "deposit_pct": deposit_pct,
            "deposit_amount": deposit_amount,
            "loan_amount": loan_amount,
            "loan_term_months": loan_term_months,
            "interest_rate_pct": round(base_rate, 2),
            "balloon_pct": balloon_pct,
            "balloon_amount": balloon_amount,
            "monthly_repayment": monthly_repayment,
            "monthly_repayment_display": f"${monthly_repayment:,.0f}",
            "finance_cost_pa": finance_cost_pa,
            "finance_cost_pa_display": f"${finance_cost_pa:,.0f}",
            "estab_fee": estab_fee_cents / 100.0,
            "admin_fee_monthly": admin_fee_cents / 100.0,
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
