"""
Default-based cost estimation for Carreb catalogue vehicles the workbook
arrived without (the 315 uncosted vehicles: exotics and other rows whose
cost columns are blank in "02 Vehicles & CORE - 29-Oct-26 FINAL LAUNCH.xlsx").

Every formula mirrors the workbook's Formulas tab step-for-step, using the
same platform tables the sync commands imported from the sheets:

  1.5  km_pa            CategoryAnnualKMBenchmark
  1.6  fuel price       StateEnergyPrice (base_fuel: petrol/diesel)
  1.7  electricity      StateEnergyPrice
  1.8  electric_share   PlatformDefault default_phev_electric_ratio (BEV=1)
  1.9  offgrid_share    PlatformDefault ev_offgrid_charging_share (0)
  2.x  running costs    StateEnergyPrice / CTPStateDefault /
       EnergyTypeCostModifier / InsuranceCategoryBenchmark /
       InsuranceStateModifier / RegistrationFeeByState /
       MaintenanceCategoryDefault / TyreCategoryDefault
  3.x  finance          FinanceDefault (PMT over term_months)
  4.x  resale           DepreciationLookup L1/L2 (+ brand table L3)
  5.x  mode COO         B=base, E=base+finance, C=base+LOST, F=base+finance+LOST
  6.x  energy-cycle CO2 NGAEmissionFactor scope2 + sheet scope-3 constants,
       FUELEF petrol 2.9 / diesel 3.39 kg/L (scope 1+3, Inputs tab)
  7.x  category bounds  CategoryScoringBounds (latest scoring_version)
  8/9  scores/stars     median of per-state clamped scores, 0.8/0.2 weighting,
       CO2 cap 315/250/190 on national median energy-cycle g/km (BEV exempt)

Estimates are marked with costing_basis "sheet_defaults_v6.4" inside every
mode dict and recorded in the vehicle's assumption_fills so they are
distinguishable from workbook-provided values.
"""

import math
import statistics
from typing import Any, Dict, Optional

from apps.vehicles.models import (
    CategoryAnnualKMBenchmark,
    CategoryScoringBounds,
    CTPStateDefault,
    DepreciationBrandModifier,
    DepreciationLookup,
    EnergyTypeCostModifier,
    FinanceDefault,
    InsuranceCategoryBenchmark,
    InsuranceStateModifier,
    MaintenanceCategoryDefault,
    NGAEmissionFactor,
    PowertrainType,
    RegistrationFeeByState,
    StateEnergyPrice,
    TyreCategoryDefault,
    Vehicle,
)
from apps.vehicles.services.core_dial import round_half_up
from apps.vehicles.services.rating_engine import calculate_monthly_repayment

STATES = ["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"]

GRID_REGION = {"NSW": "NSW/ACT", "ACT": "NSW/ACT", "WA": "WA-SWIS", "NT": "NT-DKIS"}

# Grid scope-3 factors (kg CO2e/kWh, numerically equal to g/Wh) from the
# NGA_EmissionFactors sheet; the DB table only carries scope 2.
GRID_SCOPE3 = {
    "NSW/ACT": 0.07,
    "VIC": 0.11,
    "QLD": 0.11,
    "SA": 0.03,
    "WA-SWIS": 0.10,
    "WA-NWIS": 0.09,
    "TAS": 0.03,
    "NT-DKIS": 0.13,
    "National": 0.10,
}

# Energy-cycle fuel factors, kg CO2e/L (scope 1+3) — Inputs tab engine.fuel_ef.
FUEL_EF_KG_PER_L = {"petrol": 2.9, "diesel": 3.39}
# Tailpipe-only factors used to derive a missing tailpipe figure, kg/L.
TAILPIPE_EF_KG_PER_L = {"petrol": 2.31, "diesel": 2.68}

# Platform flat default for BEV/PHEV electricity consumption (18 kWh/100km).
DEFAULT_WH_PER_KM = 180.0

PRIORITY_WP = 0.80
PRIORITY_WE = 0.20
CO2_CAP_THRESHOLDS = [(315.0, 2.4), (250.0, 3.4), (190.0, 4.4)]

MODE_LABELS = {"B": "Pure Cost", "E": "COOL Choice™", "C": "Value Later™", "F": "Full Picture"}
BAND_BY_STARS = {
    1: "Captain Carbon™",
    2: "The Detour™",
    3: "Steady Cruiser™",
    4: "Smart Move™",
    5: "Every Day Legend™",
}
COSTING_BASIS = "sheet_defaults_v6.4"
FILL_NOTE = "uncosted-cost-fill 2026-11-02"

# Latest-first preference for duplicate CategoryScoringBounds versions.
BOUNDS_VERSION_PRIORITY = ["v6.4-audit-04Nov26", "v6.4-audit-29Oct26", "v6.4-audit-27Oct26", "v6.3.4-cat-norm"]

# Powertrain → sheet energy key (EK): mild hybrids take hybrid modifiers.
EK_BY_POWERTRAIN = {
    PowertrainType.PETROL: "petrol",
    PowertrainType.DIESEL: "diesel",
    PowertrainType.HYBRID: "hev",
    PowertrainType.MILD_HYBRID: "hev",
    PowertrainType.PHEV: "phev",
    PowertrainType.BEV: "bev",
}

# EK → EnergyTypeCostModifier multiplier column.
EMOD_ATTR = {
    "petrol": "ice_petrol_multiplier",
    "diesel": "ice_diesel_multiplier",
    "hev": "hev_hybrid_multiplier",
    "bev": "bev_multiplier",
    "phev": "phev_multiplier",
}

# Powertrain → DepreciationLookup L2 key (sheet maps bev→electric etc.).
L2_KEY_BY_POWERTRAIN = {
    PowertrainType.PETROL: "petrol",
    PowertrainType.DIESEL: "diesel",
    PowertrainType.HYBRID: "hybrid",
    PowertrainType.MILD_HYBRID: "mhev",
    PowertrainType.PHEV: "phev",
    PowertrainType.BEV: "electric",
    PowertrainType.FCEV: "fcev",
}

COST_CATEGORY_OVERRIDES = {"Other": "Medium", "Upper Large SUV": "Large SUV"}


def _xround(value: float, digits: int) -> float:
    """Excel-style ROUND: half away from zero."""
    return float(round_half_up(float(value), digits))


def cost_category_for(vehicle) -> str:
    cat = (getattr(vehicle, "cost_category", "") or "").strip()
    if cat:
        return cat
    fcai = (vehicle.fcai_category or "").strip()
    return COST_CATEGORY_OVERRIDES.get(fcai, fcai)


class _Lookups:
    """All platform default tables, loaded once per run."""

    def __init__(self):
        self.energy_price = {r.state: r for r in StateEnergyPrice.objects.all()}
        self.ctp = {r.state: r.annual_ctp_cents for r in CTPStateDefault.objects.all()}
        self.ins_cat = {r.fcai_category: r.national_avg_cents_pa for r in InsuranceCategoryBenchmark.objects.all()}
        self.ins_statemod = {r.state: float(r.state_modifier) for r in InsuranceStateModifier.objects.all()}
        self.rego = {(r.fcai_category, r.state): r.annual_fee_cents for r in RegistrationFeeByState.objects.all()}
        self.maint = {r.fcai_category: r.five_year_total_cents for r in MaintenanceCategoryDefault.objects.all()}
        self.tyre = {r.fcai_category: r for r in TyreCategoryDefault.objects.all()}
        self.km = {r.fcai_category: r.est_annual_km for r in CategoryAnnualKMBenchmark.objects.all()}
        self.finance = {r.fcai_category_broad: r for r in FinanceDefault.objects.all()}
        self.emod = {r.cost_component: r for r in EnergyTypeCostModifier.objects.all()}
        self.nga = {r.grid: r for r in NGAEmissionFactor.objects.all()}
        self.dep_l1 = {r.key: float(r.modifier) for r in DepreciationLookup.objects.filter(layer_num=1)}
        self.dep_l2 = {
            r.key: float(r.modifier) for r in DepreciationLookup.objects.filter(layer_num=2)
        }
        self.brand_mod = {
            (r.brand or "").lower(): float(r.retention_multiplier)
            for r in DepreciationBrandModifier.objects.all()
        }
        self.bounds = self._load_bounds()
        # Category medians of costed peers, for fuel-consumption fallbacks.
        self._fuel_medians: Dict[tuple, Optional[float]] = {}

    def _load_bounds(self) -> Dict[tuple, CategoryScoringBounds]:
        bounds: Dict[tuple, CategoryScoringBounds] = {}
        for version in BOUNDS_VERSION_PRIORITY:
            for row in CategoryScoringBounds.objects.filter(scoring_version=version):
                bounds.setdefault((row.fcai_category, row.core_mode), row)
        return bounds

    def emod_mult(self, component: str, ek: str) -> float:
        row = self.emod.get(component)
        if not row:
            return 1.0
        attr = EMOD_ATTR.get(ek)
        val = getattr(row, attr, None) if attr else None
        return float(val) if val else 1.0

    def fuel_median(self, cost_category: str, base_fuel: str) -> Optional[float]:
        key = (cost_category, base_fuel)
        if key not in self._fuel_medians:
            values = [
                v
                for v in Vehicle.objects.filter(
                    cost_category=cost_category,
                    base_fuel=base_fuel,
                    fuel_consumption_per_100km__isnull=False,
                ).exclude(fuel_consumption_per_100km=0).values_list("fuel_consumption_per_100km", flat=True)[:400]
            ]
            self._fuel_medians[key] = float(statistics.median(values)) if values else None
        return self._fuel_medians[key]


def resolve_fuel_l100(vehicle, lookups: _Lookups, cost_category: str, base_fuel: str) -> tuple:
    """fuel_l100_used plus a note when it was estimated. Returns (value, estimated_flag)."""
    pt = vehicle.powertrain_type
    if pt == PowertrainType.BEV:
        return 0.0, False
    fuel = None
    if pt == PowertrainType.PHEV:
        fuel = vehicle.phev_fuel_consumption_l100 or vehicle.fuel_consumption_per_100km
    elif pt != PowertrainType.BEV:
        fuel = vehicle.fuel_consumption_per_100km
    if fuel:
        return float(fuel), False

    # 1) derive from tailpipe CO2 (tailpipe factors are scope-1 only)
    if vehicle.tailpipe_co2_g_per_km:
        ef = TAILPIPE_EF_KG_PER_L.get(base_fuel, TAILPIPE_EF_KG_PER_L["petrol"])
        return round(vehicle.tailpipe_co2_g_per_km / (10.0 * ef), 2), True

    # 2) category median of costed peers on the same base fuel
    median = lookups.fuel_median(cost_category, base_fuel)
    if median:
        return median, True

    # 3) any-fuel category median, then a conservative platform default
    median = lookups.fuel_median(cost_category, "petrol") if base_fuel != "petrol" else None
    if median:
        return median, True
    return 8.0, True


def resolve_wh_per_km(vehicle) -> tuple:
    """Electric consumption in Wh/km + estimated flag."""
    if vehicle.energy_consumption_wh_km:
        return float(vehicle.energy_consumption_wh_km), False
    if vehicle.electricity_consumption_per_100km:
        return float(vehicle.electricity_consumption_per_100km) * 1000.0, False
    return DEFAULT_WH_PER_KM, True


def resolve_tailpipe(vehicle, fuel_l100: float, base_fuel: str) -> tuple:
    """tailpipe CO2 g/km + estimated flag (BEVs report 0)."""
    if vehicle.tailpipe_co2_g_per_km is not None:
        return float(vehicle.tailpipe_co2_g_per_km), False
    if vehicle.powertrain_type == PowertrainType.BEV:
        return 0.0, False
    ef = TAILPIPE_EF_KG_PER_L.get(base_fuel, TAILPIPE_EF_KG_PER_L["petrol"])
    return round(fuel_l100 * 10.0 * ef, 1), True


def sibling_driveaway(vehicle) -> Optional[dict]:
    """Priced same-brand same-model variant's driveaway dict (fallback price source)."""
    siblings = (
        Vehicle.objects.filter(brand__iexact=vehicle.brand or "", model__iexact=vehicle.model or "")
        .exclude(pk=vehicle.pk)
        .exclude(driveaway_price_by_state__isnull=True)
        .exclude(driveaway_price_by_state={})
        .only("driveaway_price_by_state")
    )
    best = None
    best_count = -1
    for sib in siblings:
        priced = {k: v for k, v in (sib.driveaway_price_by_state or {}).items() if v}
        if len(priced) > best_count:
            best, best_count = priced, len(priced)
    return best or None


def compute_vehicle_estimates(vehicle: Vehicle, lookups: _Lookups) -> Optional[Dict[str, Any]]:
    """Run the full sheet-default pipeline for one vehicle. Returns per-state results."""
    driveaway_by_state = vehicle.driveaway_price_by_state or {}
    states = [s for s in STATES if driveaway_by_state.get(s)]
    price_estimated = False
    if not states:
        sibling = sibling_driveaway(vehicle)
        if not sibling:
            return None
        driveaway_by_state = {s: v for s, v in sibling.items() if v}
        states = [s for s in STATES if driveaway_by_state.get(s)]
        price_estimated = True
    if not states:
        return None

    cost_category = cost_category_for(vehicle)
    if not cost_category:
        return None
    km = lookups.km.get(cost_category)
    if not km:
        return None

    pt = vehicle.powertrain_type
    ek = EK_BY_POWERTRAIN.get(pt, "petrol")
    base_fuel = "diesel" if (vehicle.base_fuel or "").lower() == "diesel" or pt == PowertrainType.DIESEL else "petrol"

    electric_share = 0.0
    if pt == PowertrainType.BEV:
        electric_share = 1.0
    elif pt == PowertrainType.PHEV:
        from apps.config.models import PlatformDefault
        electric_share = float(PlatformDefault.get_val("default_phev_electric_ratio", 0.4) or 0.4)
    offgrid_share = 0.0

    fuel_l100, fuel_estimated = resolve_fuel_l100(vehicle, lookups, cost_category, base_fuel)
    wh_km, wh_estimated = (resolve_wh_per_km(vehicle) if electric_share > 0 else (0.0, False))
    tailpipe, tailpipe_estimated = resolve_tailpipe(vehicle, fuel_l100, base_fuel)

    # --- finance (sheet §3, same for every state except driveaway) ----------
    fcai_broad = (vehicle.fcai_broad or "").strip()
    fam = fcai_broad if fcai_broad in ("SUVs", "Light Commercial", "Heavy Commercial") else "Passenger Cars"
    fin = lookups.finance.get(fam) or next(iter(lookups.finance.values()), None)
    finance_by_state: Dict[str, Dict[str, float]] = {}

    # --- resale (sheet §4) ---------------------------------------------------
    l1_key = cost_category if cost_category.startswith("Pick-up") else (vehicle.fcai_category or cost_category)
    l1 = lookups.dep_l1.get(l1_key)
    if l1 is None:
        l1 = lookups.dep_l1.get(cost_category, 0.4)
    l2 = lookups.dep_l2.get(L2_KEY_BY_POWERTRAIN.get(pt, "unknown"), 1.0)
    l3 = lookups.brand_mod.get((vehicle.brand or "").lower(), 1.0)
    retention = round(l1 * l2 * l3, 6)

    per_state: Dict[str, Dict[str, Any]] = {}
    for state in states:
        driveaway_cents = driveaway_by_state[state]
        if isinstance(driveaway_cents, float):
            driveaway_cents = int(round_half_up(driveaway_cents * 100, 0))
        driveaway = driveaway_cents / 100.0

        prices = lookups.energy_price.get(state) or lookups.energy_price.get("NSW")
        petrol_c = float(prices.petrol_ulp95_cents_per_litre)
        diesel_c = float(prices.diesel_cents_per_litre)
        elec_c = float(prices.electricity_cents_per_kwh)
        fuel_price = diesel_c if base_fuel == "diesel" else petrol_c

        # Sheet §2 running costs (each line rounded half-up to cents).
        fuel_cost_pa = _xround(fuel_l100 * km / 100.0 * fuel_price * (1.0 - electric_share) / 100.0, 2)
        elec_cost_pa = _xround(wh_km * km * electric_share * (1.0 - offgrid_share) / 1000.0 * elec_c / 100.0, 2)

        ctp_pa = _xround((lookups.ctp.get(state, 0) / 100.0) * lookups.emod_mult("CTP Insurance", ek), 2)
        ins_base = lookups.ins_cat.get(cost_category)
        if ins_base is None:
            ins_base = lookups.ins_cat.get(cost_category.replace(" SUV", ""), 144100)
        comprehensive_pa = _xround(
            ins_base / 100.0 * lookups.ins_statemod.get(state, 1.0) * lookups.emod_mult("Comprehensive Insurance", ek), 2
        )
        rego_pa = _xround((lookups.rego.get((cost_category, state), 0) / 100.0) * lookups.emod_mult("Registration (base)", ek), 2)
        maint_pa = _xround(lookups.maint.get(cost_category, 0) / 5.0 / 100.0 * lookups.emod_mult("Maintenance", ek), 2)

        tyre = lookups.tyre.get(cost_category)
        if tyre is not None:
            sets_5yr = math.floor(round(km * 5.0 * lookups.emod_mult("Tyre Wear Rate", ek) / tyre.replacement_interval_km, 9))
            tyre_pa = _xround(sets_5yr * (tyre.cost_per_set_4_cents or tyre.annualised_cost_cents or 0) / 100.0 * lookups.emod_mult("Tyre Cost per Set", ek) / 5.0, 2)
        else:
            tyre_pa = 0.0

        base_coo = _xround(fuel_cost_pa + elec_cost_pa + ctp_pa + comprehensive_pa + rego_pa + maint_pa + tyre_pa, 2)

        # Finance (sheet §3): fees use estab_fee_default for every energy type.
        if fin and driveaway > 0:
            rate = float(fin.base_rate_pct)
            if pt in (PowertrainType.BEV, PowertrainType.PHEV):
                rate += float(fin.alt_fuel_modifier_pct or 0.0)
            loan = driveaway * (1.0 - float(fin.deposit_pct) / 100.0)
            months = int(fin.term_months or 60)
            monthly = calculate_monthly_repayment(loan, rate, months)
            interest_5yr = monthly * months - loan
            fees_5yr = (float(fin.estab_fee_default) + float(fin.admin_fee_monthly) * months) / 100.0
            finance_pa = _xround((interest_5yr + fees_5yr) / 5.0, 2)
            finance_by_state[state] = {
                "apr": rate, "loan": loan, "interest_5yr": interest_5yr,
                "fees_5yr": fees_5yr, "finance_pa": finance_pa,
            }
        else:
            finance_pa = 0.0
            finance_by_state[state] = {"apr": 0.0, "loan": 0.0, "interest_5yr": 0.0, "fees_5yr": 0.0, "finance_pa": 0.0}

        # Resale (sheet §4/5).
        resale_5yr = _xround(driveaway * retention, 2)
        resale_credit_pa = _xround(resale_5yr / 5.0, 2)
        lost_pa = _xround((driveaway - resale_5yr) / 5.0, 2)

        modes = {
            "B": base_coo,
            "E": _xround(base_coo + finance_pa, 2),
            "C": _xround(base_coo + lost_pa, 2),
            "F": _xround(base_coo + finance_pa + lost_pa, 2),
        }

        # Energy-cycle CO2 (sheet §6): scope2 from the DB grid table, scope-3
        # from the sheet constants; kg/kWh is numerically g/Wh so no /1000.
        grid = GRID_REGION.get(state, state)
        nga_row = lookups.nga.get(grid) or lookups.nga.get("National")
        s2 = float(nga_row.scope2_factor_kgco2e_per_kwh) if nga_row else 0.59
        s3 = GRID_SCOPE3.get(grid, GRID_SCOPE3["National"])
        fuelef = FUEL_EF_KG_PER_L.get(base_fuel, FUEL_EF_KG_PER_L["petrol"])
        co2_fuel = fuel_l100 * 10.0 * fuelef * (1.0 - electric_share)
        co2_grid = wh_km * electric_share * (1.0 - offgrid_share) * (s2 + s3)
        co2_energy = _xround(co2_fuel + co2_grid, 1)
        annual_co2_kg = int(round_half_up(co2_energy * km / 1000.0, 0))
        tailpipe_pa_kg = int(round_half_up(tailpipe * km / 1000.0, 0))

        per_state[state] = {
            "driveaway": driveaway,
            "components": {
                "fuel_cost_pa": fuel_cost_pa,
                "electricity_cost_pa": elec_cost_pa,
                "ctp_pa": ctp_pa,
                "comprehensive_pa": comprehensive_pa,
                "registration_pa": rego_pa,
                "maintenance_pa": maint_pa,
                "tyre_cost_pa": tyre_pa,
            },
            "base_coo_pa": base_coo,
            "finance_pa": finance_pa,
            "finance_detail": finance_by_state[state],
            "resale_5yr": resale_5yr,
            "resale_credit_pa": resale_credit_pa,
            "lost_pa": lost_pa,
            "mode_coo_pa": modes,
            "co2": {
                "co2_energy_cycle_g_km": co2_energy,
                "co2_fuel_g_km": _xround(co2_fuel, 1),
                "co2_grid_g_km": _xround(co2_grid, 1),
                "annual_co2_kg": annual_co2_kg,
                "tailpipe_pa_kg": tailpipe_pa_kg,
            },
        }

    # --- national scores (sheet §7-9) ---------------------------------------
    fcai_category = vehicle.fcai_category or cost_category
    national: Dict[str, Dict[str, Any]] = {}
    raw_price_medians: Dict[str, float] = {}
    raw_emissions_medians: Dict[str, float] = {}

    for mode in ("B", "E", "C", "F"):
        bound = lookups.bounds.get((fcai_category, mode))
        row_scores = []
        raw_scores = []
        emissions_scores = []
        raw_emissions = []
        for state in states:
            coo = per_state[state]["mode_coo_pa"][mode]
            co2 = per_state[state]["co2"]["co2_energy_cycle_g_km"]
            if bound and bound.cat_max_coo > bound.cat_min_coo:
                raw = 1.0 - (coo - bound.cat_min_coo) / (bound.cat_max_coo - bound.cat_min_coo)
            else:
                raw = 0.5
            row_scores.append(min(1.0, max(0.0, raw)))
            raw_scores.append(raw)
            if bound and bound.cat_max_co2 > bound.cat_min_co2:
                raw_e = 1.0 - (co2 - bound.cat_min_co2) / (bound.cat_max_co2 - bound.cat_min_co2)
            else:
                raw_e = 0.5
            emissions_scores.append(min(1.0, max(0.0, raw_e)))
            raw_emissions.append(raw_e)

        price_score = round(float(statistics.median(row_scores)), 6)
        emissions_score = round(float(statistics.median(emissions_scores)), 6)
        raw_price_medians[mode] = float(statistics.median(raw_scores))
        raw_emissions_medians[mode] = float(statistics.median(raw_emissions))
        core_score = round(PRIORITY_WP * price_score + PRIORITY_WE * emissions_score, 6)
        rating_1dp = float(round_half_up(core_score * 5.0, 1))

        national[mode] = {
            "price_score": price_score,
            "emissions_score": emissions_score,
            "core_score": core_score,
            "core_rating_1dp": rating_1dp,
        }

    # CO2 cap reads the national median energy-cycle g/km on Mode B; BEVs exempt.
    energy_national = float(statistics.median(
        per_state[s]["co2"]["co2_energy_cycle_g_km"] for s in states
    ))
    cap_tier = None
    if pt != PowertrainType.BEV:
        for threshold, tier in CO2_CAP_THRESHOLDS:
            if energy_national >= threshold:
                cap_tier = tier
                break
    for mode in ("B", "E", "C", "F"):
        rating = national[mode]["core_rating_1dp"]
        capped = min(rating, cap_tier) if cap_tier else rating
        stars = max(1, int(round_half_up(capped, 0)))
        national[mode]["core_rating_capped"] = capped
        national[mode]["stars"] = stars
        national[mode]["band_name"] = BAND_BY_STARS[stars]

    is_outlier = any(
        med < 0.0 or med > 1.0
        for med in list(raw_price_medians.values()) + list(raw_emissions_medians.values())
    )

    return {
        "cost_category": cost_category,
        "annual_km": km,
        "base_fuel": base_fuel,
        "energy_key": ek,
        "electric_share": electric_share,
        "offgrid_share": offgrid_share,
        "fuel_l100_used": fuel_l100,
        "fuel_estimated": fuel_estimated,
        "wh_per_km": wh_km,
        "wh_estimated": wh_estimated,
        "tailpipe": tailpipe,
        "tailpipe_estimated": tailpipe_estimated,
        "retention": retention,
        "price_estimated": price_estimated,
        "driveaway_used": driveaway_by_state,
        "energy_cycle_national": energy_national,
        "states": per_state,
        "national": national,
        "co2_cap_tier": cap_tier,
        "is_scoring_outlier": is_outlier,
    }


def build_mode_data(vehicle: Vehicle, result: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the mode_data_by_state payload mirroring costed vehicles."""
    mode_data_by_state: Dict[str, Any] = {}
    tier_labels = {2.4: "≥315 g/km → 2.4", 3.4: "250–314 g/km → 3.4", 4.4: "190–249 g/km → 4.4"}
    cap_tier = result["co2_cap_tier"]
    for state, st in result["states"].items():
        state_payload: Dict[str, Any] = {}
        for mode in ("B", "E", "C", "F"):
            nat = result["national"][mode]
            state_payload[mode] = {
                "stars": float(nat["stars"]),
                "band_name": nat["band_name"],
                "core_score": nat["core_score"],
                "mode_label": MODE_LABELS[mode],
                "mode_coo_pa": st["mode_coo_pa"][mode],
                "mode_5yr_coo": _xround(st["mode_coo_pa"][mode] * 5.0, 2),
                "price_score": nat["price_score"],
                "co2_cap_tier": tier_labels.get(cap_tier, "none"),
                "annual_co2_kg": float(st["co2"]["annual_co2_kg"]),
                "core_rating_1dp": nat["core_rating_1dp"],
                "emissions_score": nat["emissions_score"],
                "finance_cost_pa": st["finance_pa"],
                "resale_credit_pa": st["resale_credit_pa"],
                "core_rating_capped": nat["core_rating_capped"],
                # CO2/energy detail (mirrors the 21-Oct costed columns).
                "electric_share": result["electric_share"],
                "offgrid_share": result["offgrid_share"],
                "fuel_l100_used": result["fuel_l100_used"],
                "co2_fuel_g_km": st["co2"]["co2_fuel_g_km"],
                "co2_grid_g_km": st["co2"]["co2_grid_g_km"],
                "co2_tailpipe_pa_kg": float(st["co2"]["tailpipe_pa_kg"]),
                "costing_basis": COSTING_BASIS,
            }
        mode_data_by_state[state] = state_payload
    return mode_data_by_state


def apply_estimates(vehicle: Vehicle, result: Dict[str, Any], commit: bool = True) -> Dict[str, Any]:
    """Write computed estimates into the vehicle's cost/scoring fields."""
    states = result["states"]
    dollars = lambda v: int(round_half_up(v * 100, 0))

    vehicle.cost_category = result["cost_category"]
    vehicle.annual_km_default = result["annual_km"]
    vehicle.tailpipe_co2_g_per_km = result["tailpipe"]
    vehicle.co2_energy_cycle_g_per_km = result["energy_cycle_national"]
    if result["wh_estimated"] and not vehicle.energy_consumption_wh_km:
        vehicle.energy_consumption_wh_km = result["wh_per_km"]

    vehicle.fuel_cost_by_state = {s: dollars(st["components"]["fuel_cost_pa"]) for s, st in states.items()}
    vehicle.electricity_cost_by_state = {s: dollars(st["components"]["electricity_cost_pa"]) for s, st in states.items()}
    vehicle.insurance_estimate_by_state = {s: dollars(st["components"]["comprehensive_pa"]) for s, st in states.items()}
    vehicle.ctp_by_state = {s: dollars(st["components"]["ctp_pa"]) for s, st in states.items()}
    vehicle.registration_by_state = {s: dollars(st["components"]["registration_pa"]) for s, st in states.items()}
    vehicle.base_coo_by_state = {s: dollars(st["base_coo_pa"]) for s, st in states.items()}
    vehicle.components_sum_by_state = {
        s: dollars(sum(st["components"].values())) for s, st in states.items()
    }
    vehicle.total_5yr_cost_of_ownership_by_state = {
        s: dollars(st["mode_coo_pa"]["B"] * 5.0) for s, st in states.items()
    }
    nsw = states.get("NSW") or next(iter(states.values()))
    vehicle.servicing_5yr_estimate = dollars(nsw["components"]["maintenance_pa"] * 5.0)
    vehicle.tyre_replacement_estimate = dollars(nsw["components"]["tyre_cost_pa"] * 5.0)
    vehicle.resale_value_5yr_estimate = dollars(nsw["resale_5yr"])
    vehicle.finance_apr_pct = nsw["finance_detail"]["apr"]
    vehicle.total_interest_5yr = dollars(nsw["finance_detail"]["interest_5yr"])
    vehicle.finance_fees_5yr = dollars(nsw["finance_detail"]["fees_5yr"])
    vehicle.finance_cost_5yr = dollars(nsw["finance_detail"]["interest_5yr"] + nsw["finance_detail"]["fees_5yr"])
    vehicle.retention_factor = result["retention"]

    if result.get("price_estimated") and not any((vehicle.driveaway_price_by_state or {}).values()):
        vehicle.driveaway_price_by_state = result["driveaway_used"]

    vehicle.mode_data_by_state = build_mode_data(vehicle, result)
    vehicle.is_scoring_outlier = result["is_scoring_outlier"]
    vehicle.scoring_version = "v6.4-estimates-02Nov26"

    notes = []
    if result.get("price_estimated"):
        notes.append("driveaway from sibling variant")
    if result["fuel_estimated"]:
        notes.append("fuel consumption estimated")
    if result["tailpipe_estimated"]:
        notes.append("tailpipe CO2 estimated")
    if result["wh_estimated"]:
        notes.append("electric consumption defaulted")
    existing = (vehicle.assumption_fills or "").strip()
    addition = FILL_NOTE + (f" ({', '.join(notes)})" if notes else "")
    if FILL_NOTE not in existing:
        vehicle.assumption_fills = f"{existing}; {addition}".strip("; ")

    if commit:
        vehicle.save()
    return {
        "cost_category": result["cost_category"],
        "base_coo_nsw": states["NSW"]["base_coo_pa"] if "NSW" in states else None,
        "mode_coo_nsw": {m: states["NSW"]["mode_coo_pa"][m] for m in ("B", "E", "C", "F")} if "NSW" in states else None,
        "stars": {m: result["national"][m]["stars"] for m in ("B", "E", "C", "F")},
        "energy_cycle_national": result["energy_cycle_national"],
        "estimated_fields": notes,
    }


def find_uncosted_vehicles():
    """Catalogue vehicles with no mode_coo_pa in any state/mode."""
    candidates = Vehicle.objects.exclude(mode_data_by_state__isnull=True).exclude(mode_data_by_state={}).only(
        "id", "mode_data_by_state"
    ).iterator()
    uncosted = []
    for vehicle in candidates:
        md = vehicle.mode_data_by_state or {}
        has_cost = any(
            isinstance(m, dict) and m.get("mode_coo_pa") is not None
            for modes in md.values()
            if isinstance(modes, dict)
            for m in modes.values()
        )
        if not has_cost:
            uncosted.append(vehicle.pk)
    return Vehicle.objects.filter(pk__in=uncosted)
