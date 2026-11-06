import math
import re
from typing import Dict, Any, Optional

from rest_framework import views, status, serializers
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from django.db.models import Avg, Count, Q


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

class CostBreakdownSerializer(serializers.Serializer):
    fuel_or_electricity = serializers.FloatField(help_text="Estimated annual fuel or electricity cost in dollars")
    fuel_or_electricity_display = serializers.CharField(help_text="Formatted fuel or electricity cost, e.g. $2,477")
    insurance = serializers.FloatField(help_text="Estimated annual insurance cost (comprehensive + CTP) in dollars")
    insurance_display = serializers.CharField(help_text="Formatted insurance cost, e.g. $2,322")
    registration = serializers.FloatField(help_text="Estimated annual registration cost in dollars")
    registration_display = serializers.CharField(help_text="Formatted registration cost, e.g. $693")
    maintenance = serializers.FloatField(help_text="Estimated annual servicing and maintenance cost in dollars")
    maintenance_display = serializers.CharField(help_text="Formatted maintenance cost, e.g. $279")
    tyres = serializers.FloatField(help_text="Estimated annual tyre wear and replacement cost in dollars")
    tyres_display = serializers.CharField(help_text="Formatted tyre cost, e.g. $190")
    ev_levy = serializers.FloatField(default=0.0, help_text="Estimated annual EV road user levy in dollars (where applicable)")
    ev_levy_display = serializers.CharField(default="$0", help_text="Formatted EV levy, e.g. $0")


class CostEstimatorDataSerializer(serializers.Serializer):
    fuel_type = serializers.CharField(help_text="Normalized fuel/powertrain type (e.g. diesel, petrol, hybrid, electric)")
    fuel_type_display = serializers.CharField(help_text="User-facing fuel type label, e.g. Diesel")
    annual_km = serializers.IntegerField(help_text="Annual kilometres evaluated, e.g. 10000")
    annual_km_display = serializers.CharField(help_text="Formatted annual kilometres, e.g. 10,000 km/year")
    state = serializers.CharField(help_text="Australian state or territory, e.g. NSW")
    category = serializers.CharField(allow_null=True, required=False, help_text="Optional vehicle category, e.g. SUVs, Passenger Cars")
    sample_size = serializers.IntegerField(help_text="Number of catalogue vehicle models benchmarked")
    
    estimated_annual_running_cost = serializers.FloatField(help_text="Total estimated annual running cost in dollars")
    estimated_annual_running_cost_display = serializers.CharField(help_text="Formatted annual running cost, e.g. $5,000 or $5,962")
    
    ev_annual_running_cost = serializers.FloatField(help_text="Benchmark annual running cost for an equivalent EV in dollars")
    ev_annual_running_cost_display = serializers.CharField(help_text="Formatted EV annual running cost, e.g. $4,297")
    
    potential_saving_vs_ev = serializers.FloatField(help_text="Estimated potential annual saving compared to EV in dollars (0 if EV)")
    potential_saving_vs_ev_display = serializers.CharField(help_text="Formatted saving against EV, e.g. $1,665/yr")

    potential_saving_vs_petrol = serializers.FloatField(help_text="Estimated potential annual saving compared to petrol vehicle in dollars (primarily for EVs)")
    potential_saving_vs_petrol_display = serializers.CharField(help_text="Formatted saving against petrol, e.g. $702/yr")
    
    equivalent_grocery_weeks = serializers.IntegerField(help_text="Number of weeks of average Australian grocery bills represented by savings")
    grocery_weekly_baseline = serializers.FloatField(help_text="Average weekly grocery bill baseline in dollars ($75/week)")
    grocery_comparison_text = serializers.CharField(help_text="User-facing comparison sentence for UI display")
    
    cost_breakdown = CostBreakdownSerializer(help_text="Granular itemized cost breakdown")
    
    summary_disclaimer = serializers.CharField(help_text="One-line summary for card footer")
    disclaimer = serializers.CharField(help_text="Comprehensive legal and methodology disclaimer")


class CostEstimatorResponseSerializer(serializers.Serializer):
    status = serializers.CharField(default="success")
    data = CostEstimatorDataSerializer()


class CostEstimatorRequestSerializer(serializers.Serializer):
    fuel_type = serializers.CharField(required=False, default="diesel", help_text="Vehicle fuel/powertrain: petrol, diesel, hybrid (HEV), mild_hybrid, phev, electric/ev")
    annual_km = serializers.CharField(required=False, default="15000", help_text="Annual km driven: e.g. 10000, '10,000', '10,000+ km'")
    state = serializers.CharField(required=False, default="NSW", help_text="Australian state code: NSW, VIC, QLD, WA, SA, TAS, ACT, NT")
    category = serializers.CharField(required=False, allow_blank=True, default="", help_text="Optional category filter: SUV, Passenger, Commercial")


# ---------------------------------------------------------------------------
# Business Logic & Calculation Engine
# ---------------------------------------------------------------------------

AU_VALID_STATES = {"NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"}
GROCERY_WEEKLY_BASELINE = 207.0  # Average household grocery spend, Finder Consumer Sentiment Tracker, March 2026

def parse_annual_km(raw_km: Any, default: int = 15000) -> int:
    """
    Sanitizes arbitrary km inputs like '10,000+ km', '20000', 10000 into a bounded integer.
    """
    if raw_km is None:
        return default
    if isinstance(raw_km, (int, float)):
        val = int(raw_km)
    else:
        digits = re.sub(r'[^\d]', '', str(raw_km))
        val = int(digits) if digits else default

    # Clamping between 1,000 km and 150,000 km
    return max(1000, min(150000, val))


def normalize_fuel_type(raw_fuel: Optional[str]) -> str:
    """Normalize a fuel query string to one of the dataset's powertrain
    buckets: 'petrol', 'diesel', 'hybrid' (HEV only), 'mild_hybrid',
    'phev', 'electric' (BEV/FCEV).

    PHEV and mild hybrid are their own types — never lumped into 'hybrid'.
    Raises ValueError for unknown types (the view turns that into a 400);
    there is no silent petrol fallback.
    """
    if not raw_fuel:
        return "diesel"
    val = str(raw_fuel).lower().strip().replace('-', '_')
    aliases = {
        'petrol': 'petrol', 'gasoline': 'petrol',
        'diesel': 'diesel',
        'hybrid': 'hybrid', 'hev': 'hybrid', 'full_hybrid': 'hybrid',
        'mild_hybrid': 'mild_hybrid', 'mhev': 'mild_hybrid',
        'phev': 'phev', 'plug_in_hybrid': 'phev', 'plug_in hybrid': 'phev', 'plug_in': 'phev',
        'electric': 'electric', 'ev': 'electric', 'bev': 'electric',
    }
    if val in aliases:
        return aliases[val]
    raise ValueError(
        f"Unknown fuel_type '{raw_fuel}'. Expected one of: "
        "petrol, diesel, hybrid, mild_hybrid, phev, electric.")



def get_fuel_type_display(normalized_fuel: str) -> str:
    labels = {
        "diesel": "Diesel",
        "petrol": "Petrol",
        "hybrid": "Hybrid",
        "mild_hybrid": "Mild hybrid",
        "phev": "Plug-in hybrid",
        "electric": "Electric (EV)",
    }
    return labels.get(normalized_fuel, normalized_fuel.capitalize())


def _query_aggregated_components(fuel_norm: str, state: str, category: Optional[str] = None) -> Dict[str, Any]:
    """Average component costs from the CURRENT CORE Dial batch — i.e. the
    live rows of the current dataset load only (suppressed listings never
    enter the dial). Sample sizes are distinct live listings per state.

    Fuel buckets follow the dataset's energy_norm vocabulary: petrol,
    diesel, bev (+fcev) as electric, and FULL hybrids (hev) as hybrid —
    mild hybrids (mhev) and PHEVs are separate and not counted as hybrid.
    """
    from apps.vehicles.models import CoreDialBatch, CoreDialRow

    batch = CoreDialBatch.objects.filter(is_current=True).first()
    qs = CoreDialRow.objects.filter(batch=batch, state__iexact=state) \
        if batch else CoreDialRow.objects.none()

    if category:
        cat_clean = category.strip().lower()
        cat_qs = qs.filter(
            Q(vehicle__fcai_broad__icontains=cat_clean)
            | Q(vehicle__fcai_category__icontains=cat_clean))
        if cat_qs.exists():
            qs = cat_qs

    energy_norms = {
        'petrol': ['petrol'],
        'diesel': ['diesel'],
        'electric': ['bev', 'fcev'],
        'hybrid': ['hev'],              # full hybrids only
        'mild_hybrid': ['mhev'],        # mild hybrids are their own type
        'phev': ['phev'],               # plug-in hybrids are their own type
    }.get(fuel_norm, ['petrol'])
    fuel_qs = qs.filter(vehicle__energy_norm__in=energy_norms)

    agg = fuel_qs.aggregate(
        sample_count=Count('version_id', distinct=True),
        avg_fuel=Avg('fuel_cents'),
        avg_elec=Avg('electricity_cents'),
        avg_ctp=Avg('ctp_cents'),
        avg_comp=Avg('comprehensive_cents'),
        avg_rego=Avg('registration_cents'),
        avg_maint=Avg('servicing_cents'),
        avg_tyre=Avg('tyres_cents'),
        avg_ev_levy=Avg('road_user_charge_cents'),
        avg_km=Avg('vehicle__annual_km_default'),
    )
    return agg


def calculate_cost_estimate(
    raw_fuel: Optional[str] = "diesel",
    raw_km: Any = 15000,
    raw_state: Optional[str] = "NSW",
    raw_category: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculates estimated annual vehicle running costs and comparisons backed by real COO breakdown DB data.
    """
    normalized_fuel = normalize_fuel_type(raw_fuel)
    fuel_type_display = get_fuel_type_display(normalized_fuel)
    annual_km = parse_annual_km(raw_km, default=15000)

    # State validation
    state_candidate = (raw_state or "NSW").strip().upper()
    state = state_candidate if state_candidate in AU_VALID_STATES else "NSW"
    category = raw_category.strip() if raw_category else None

    # Query target vehicle data
    target_agg = _query_aggregated_components(normalized_fuel, state, category)
    sample_size = target_agg.get("sample_count") or 1
    km_ref = float(target_agg.get("avg_km") or 15000)
    scale_factor = annual_km / km_ref

    # Variable costs scaled with km
    fuel_cost = ((target_agg.get("avg_fuel") or 0) / 100.0) * scale_factor
    elec_cost = ((target_agg.get("avg_elec") or 0) / 100.0) * scale_factor
    fuel_or_electricity = round(fuel_cost + elec_cost, 2)
    maintenance = round(((target_agg.get("avg_maint") or 0) / 100.0) * scale_factor, 2)
    tyres = round(((target_agg.get("avg_tyre") or 0) / 100.0) * scale_factor, 2)
    ev_levy = round(((target_agg.get("avg_ev_levy") or 0) / 100.0) * scale_factor, 2)

    # Fixed statutory costs
    insurance = round(((target_agg.get("avg_comp") or 0) + (target_agg.get("avg_ctp") or 0)) / 100.0, 2)
    registration = round(((target_agg.get("avg_rego") or 0)) / 100.0, 2)

    total_running_cost = round(fuel_or_electricity + insurance + registration + maintenance + tyres + ev_levy, 2)

    # Query EV baseline for comparison
    ev_agg = _query_aggregated_components("electric", state, category)
    ev_km_ref = float(ev_agg.get("avg_km") or 15000)
    ev_scale = annual_km / ev_km_ref
    ev_fuel_elec = round(((ev_agg.get("avg_fuel") or 0) + (ev_agg.get("avg_elec") or 0)) / 100.0 * ev_scale, 2)
    ev_maint = round(((ev_agg.get("avg_maint") or 0) / 100.0) * ev_scale, 2)
    ev_tyres = round(((ev_agg.get("avg_tyre") or 0) / 100.0) * ev_scale, 2)
    ev_levy_cost = round(((ev_agg.get("avg_ev_levy") or 0) / 100.0) * ev_scale, 2)
    ev_insurance = round(((ev_agg.get("avg_comp") or 0) + (ev_agg.get("avg_ctp") or 0)) / 100.0, 2)
    ev_registration = round(((ev_agg.get("avg_rego") or 0)) / 100.0, 2)
    ev_total = round(ev_fuel_elec + ev_maint + ev_tyres + ev_insurance + ev_registration + ev_levy_cost, 2)

    # Query Petrol baseline for EV driver comparison
    petrol_agg = _query_aggregated_components("petrol", state, category)
    petrol_km_ref = float(petrol_agg.get("avg_km") or 15000)
    petrol_scale = annual_km / petrol_km_ref
    petrol_fuel = round(((petrol_agg.get("avg_fuel") or 0) / 100.0) * petrol_scale, 2)
    petrol_maint = round(((petrol_agg.get("avg_maint") or 0) / 100.0) * petrol_scale, 2)
    petrol_tyres = round(((petrol_agg.get("avg_tyre") or 0) / 100.0) * petrol_scale, 2)
    petrol_insurance = round(((petrol_agg.get("avg_comp") or 0) + (petrol_agg.get("avg_ctp") or 0)) / 100.0, 2)
    petrol_rego = round(((petrol_agg.get("avg_rego") or 0)) / 100.0, 2)
    petrol_total = round(petrol_fuel + petrol_maint + petrol_tyres + petrol_insurance + petrol_rego, 2)

    # Savings calculations — signed. A type that costs more than its
    # comparison reports an extra cost, never a clamped "$0 saving".
    potential_saving_vs_ev = round(total_running_cost - ev_total, 2)
    potential_saving_vs_petrol = round(petrol_total - total_running_cost, 2)

    if normalized_fuel == "electric":
        saving_metric = potential_saving_vs_petrol
        comparison_label = "petrol"
    else:
        saving_metric = potential_saving_vs_ev
        comparison_label = "EV"

    if saving_metric > 0:
        # Half-up rounding (Finder baseline 207): floor(x + 0.5), because
        # Python's round() banks (round(4.5) == 4).
        grocery_weeks = max(0, math.floor(saving_metric / GROCERY_WEEKLY_BASELINE + 0.5))
        grocery_comparison_text = (
            f"That potential estimated saving is about the same as {grocery_weeks} "
            f"week{'s' if grocery_weeks != 1 else ''} of the average household grocery shop."
        ) if grocery_weeks > 0 else ""
        comparison_phrase = (
            f"Estimated potential saving against {comparison_label}: "
            f"~${round(saving_metric):,}/yr")
    else:
        grocery_weeks = 0
        grocery_comparison_text = ""
        comparison_phrase = (
            f"Estimated extra cost against {comparison_label}: "
            f"~${round(abs(saving_metric)):,}/yr")

    summary_disclaimer = (
        f"Estimate · Average {fuel_type_display.lower()} vehicle · {annual_km:,} km/year ({state}) · "
        f"Individual costs vary significantly · {comparison_phrase}"
    )

    disclaimer = (
        "All figures are indicative only — individual running costs vary based on driving style, "
        "location, insurer, vehicle condition, fuel pricing, and electricity tariffs."
    )

    cost_breakdown = {
        "fuel_or_electricity": fuel_or_electricity,
        "fuel_or_electricity_display": f"${round(fuel_or_electricity):,}",
        "insurance": insurance,
        "insurance_display": f"${round(insurance):,}",
        "registration": registration,
        "registration_display": f"${round(registration):,}",
        "maintenance": maintenance,
        "maintenance_display": f"${round(maintenance):,}",
        "tyres": tyres,
        "tyres_display": f"${round(tyres):,}",
        "ev_levy": ev_levy,
        "ev_levy_display": f"${round(ev_levy):,}",
    }

    return {
        "fuel_type": normalized_fuel,
        "fuel_type_display": fuel_type_display,
        "annual_km": annual_km,
        "annual_km_display": f"{annual_km:,} km/year",
        "state": state,
        "category": category,
        "sample_size": sample_size,
        "estimated_annual_running_cost": total_running_cost,
        "estimated_annual_running_cost_display": f"${round(total_running_cost):,}",
        "ev_annual_running_cost": ev_total,
        "ev_annual_running_cost_display": f"${round(ev_total):,}",
        "potential_saving_vs_ev": potential_saving_vs_ev,
        "potential_saving_vs_ev_display": f"${round(potential_saving_vs_ev):,}/yr",
        "potential_saving_vs_petrol": potential_saving_vs_petrol,
        "potential_saving_vs_petrol_display": f"${round(potential_saving_vs_petrol):,}/yr",
        "equivalent_grocery_weeks": grocery_weeks,
        "grocery_weekly_baseline": GROCERY_WEEKLY_BASELINE,
        "grocery_comparison_text": grocery_comparison_text,
        "cost_breakdown": cost_breakdown,
        "summary_disclaimer": summary_disclaimer,
        "disclaimer": disclaimer,
    }


# ---------------------------------------------------------------------------
# API View
# ---------------------------------------------------------------------------

class VehicleCostEstimatorAPIView(views.APIView):
    """
    GET /api/v1/vehicles/estimate-cost/
    GET /api/vehicles/estimate-cost/

    Interactive Cost Estimator API:
    Calculates estimated annual vehicle running costs, itemized cost breakdowns
    (fuel/power, insurance, registration, maintenance, tyres), potential savings
    against electric vehicles, and grocery equivalency benchmarks.

    Query Parameters:
      - fuel_type (optional, str): 'petrol', 'diesel', 'hybrid' (HEV only), 'mild_hybrid',
        'phev', 'electric' / 'ev'. Unknown values return 400. Default: 'diesel'.
      - annual_km (optional, int/str): e.g. 10000, 15000, 20000, '10,000+ km'. Default: 15000.
      - state (optional, str): Australian state code ('NSW', 'VIC', 'QLD', etc.). Default: 'NSW'.
      - category (optional, str): Optional FCAI category / vehicle type filter (e.g. 'SUV', 'Passenger').
    """
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        serializer = CostEstimatorRequestSerializer(data=request.query_params)
        if not serializer.is_valid():
            return Response(
                {
                    "status": "error",
                    "message": "Invalid request query parameters",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        try:
            result = calculate_cost_estimate(
                raw_fuel=data.get("fuel_type"),
                raw_km=data.get("annual_km"),
                raw_state=data.get("state"),
                raw_category=data.get("category"),
            )
        except ValueError as exc:
            return Response(
                {"status": "error", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = CostEstimatorResponseSerializer({"status": "success", "data": result})
        return Response(response_serializer.data, status=status.HTTP_200_OK)
