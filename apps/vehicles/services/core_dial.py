"""CORE Dial (v6.4) computation — Pure Cost (Mode B) only.

This module is the single source of truth for the Dial algorithm. It is pure
(server never re-scores on a slider move; the browser re-weights from the
dataset using the same constants). Everything rounds half-up like Excel ROUND
— never use Python round() here (banker's rounding gets halves wrong).

Spec: "CORE Dial — Build Prompt (v6.4, Pure Cost)".
"""
import math
import statistics

# --- The eight valid state codes (section 8) -------------------------------
AU_STATES = ('ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA')

# --- Band names come from config, never from the data (section 1) ----------
BAND_NAMES = {
    1: 'Captain Carbon™',
    2: 'The Detour™',
    3: 'Steady Cruiser™',
    4: 'Smart Move™',
    5: 'Every Day Legend™',
}

# --- My Priority: five fixed stops (section 3, D28) ------------------------
# stop -> (W(price), W(emissions)). The stop number (1-5) is stored/sent,
# never float weights.
PRIORITY_STOPS = {
    1: (0.80, 0.20),
    2: (0.65, 0.35),
    3: (0.50, 0.50),
    4: (0.35, 0.65),
    5: (0.20, 0.80),
}
DEFAULT_STOP = 1

PRIORITY_STOP_HELPERS = {
    1: "We'll focus on estimated ownership costs, with some weight on carbon impact.",
    2: "We'll weigh estimated ownership costs a little more than carbon impact.",
    3: "We'll balance estimated ownership costs and carbon impact equally.",
    4: "We'll weigh carbon impact a little more than estimated ownership costs.",
    5: "We'll focus on carbon impact, with some weight on estimated ownership costs.",
}

# --- My Budget (section 4) --------------------------------------------------
BUDGET_MIN_DOLLARS = 20_000
BUDGET_MAX_DOLLARS = 200_000
BUDGET_STEP_DOLLARS = 5_000
WINDOW_DOLLARS = 15_000
WINDOW_TOP_DOLLARS = 185_000  # at $200,000+: everything from $185,000 up


def round_half_up(x, dp=0):
    """Excel ROUND: half away from zero on positive numbers."""
    f = 10 ** dp
    return math.floor(x * f + 0.5 + 1e-9) / f


def dollars_to_cents(dollars):
    """Convert dollars to integer cents once, at the boundary (rule 5)."""
    return int(round_half_up(float(dollars) * 100, 0))


def co2_cap_for(powertrain, co2_g_per_km):
    """Rating cap from tailpipe CO2 (section 5). BEV/FCEV are never capped."""
    if powertrain in ('bev', 'fcev'):
        return None
    co2 = float(co2_g_per_km or 0)
    if co2 >= 250:
        return 2.4
    if co2 >= 200:
        return 3.4
    if co2 >= 150:
        return 4.4
    return None


def budget_window_cents(budget_dollars):
    """±$15,000 window, both ends included; $185,000+ at the top (section 4).

    Returns (lo_cents, hi_cents); hi_cents is None for no upper bound.
    """
    budget = int(budget_dollars)
    if budget >= BUDGET_MAX_DOLLARS:
        return dollars_to_cents(WINDOW_TOP_DOLLARS), None
    lo = max(0, budget - WINDOW_DOLLARS)
    return dollars_to_cents(lo), dollars_to_cents(budget + WINDOW_DOLLARS)


def budget_range_line(budget_dollars):
    """The exact 'Cars priced ...' range line (section 4)."""
    budget = int(budget_dollars)
    if budget >= BUDGET_MAX_DOLLARS:
        return f'Cars priced ${WINDOW_TOP_DOLLARS:,} and up'
    lo = max(BUDGET_MIN_DOLLARS, budget - WINDOW_DOLLARS)
    hi = budget + WINDOW_DOLLARS
    if lo <= BUDGET_MIN_DOLLARS:
        return f'Cars priced up to ${hi:,}'
    return f'Cars priced ${lo:,}–${hi:,}'


def is_valid_budget(budget):
    """Whole dollars, multiple of 5,000, in 20,000–200,000 (section 7, 400s)."""
    if isinstance(budget, bool) or not isinstance(budget, int):
        return False
    return (BUDGET_MIN_DOLLARS <= budget <= BUDGET_MAX_DOLLARS
            and budget % BUDGET_STEP_DOLLARS == 0)


def rate_version(price_score, emissions_score, co2_cap, stop):
    """Section 5 rating formula at a fixed stop. Returns (rating_1dp, band)."""
    wp, we = PRIORITY_STOPS[stop]
    core = wp * float(price_score) + we * float(emissions_score)
    rating = min(round_half_up(core * 5, 1),
                 co2_cap if co2_cap is not None else math.inf)
    band = max(1, int(round_half_up(rating, 0)))
    return rating, band


def median_or_none(values):
    """Middle value, or mean of the two middle ones when even (section 6.2)."""
    values = sorted(values)
    if not values:
        return None
    return statistics.median(values)


def compute_bands(rows, budget_dollars, stop):
    """The Dial computation (section 6.4) over dial rows for ONE state.

    `rows` is an iterable of objects (CoreDialRow or duck-typed) carrying:
    version_id, model_id, make, driveaway_cents, coo_pa_cents, annual_co2_kg,
    price_score, emissions_score, co2_cap.

    Returns {band: {'models': [{row, rating}], 'count', 'coo_pa_cents',
    'annual_co2_kg'}}. Each model appears at most once per band; a model whose
    versions land in two bands counts in both.
    """
    lo_cents, hi_cents = budget_window_cents(budget_dollars)

    in_window = [
        r for r in rows
        if r.driveaway_cents is not None
        and r.driveaway_cents >= lo_cents
        and (hi_cents is None or r.driveaway_cents <= hi_cents)
    ]

    rated = []
    for r in in_window:
        rating, band = rate_version(r.price_score, r.emissions_score, r.co2_cap, stop)
        rated.append((r, rating, band))

    bands = {}
    for b in range(1, 6):
        # Rank: rating DESC, then coo_pa_cents ASC, then version_id ASC (6.1)
        ranked = sorted(
            (t for t in rated if t[2] == b),
            key=lambda t: (-t[1], t[0].coo_pa_cents, t[0].version_id),
        )
        seen, models = set(), []
        for row, rating, _ in ranked:
            if row.model_id in seen:
                continue
            seen.add(row.model_id)
            models.append({'row': row, 'rating': rating})
        bands[b] = {
            'models': models,
            'count': len(models),
            'coo_pa_cents': median_or_none([m['row'].coo_pa_cents for m in models]),
            'annual_co2_kg': median_or_none([m['row'].annual_co2_kg for m in models]),
        }
    return bands


def initial_needle_band(bands):
    """On opening: highest band with at least one model, else 3 (section 6.3)."""
    for b in range(5, 0, -1):
        if bands[b]['count'] > 0:
            return b
    return 3


def select_matches(band_models, limit=10):
    """Green-button fill (section 7): pass 1 one model per make, pass 2 a
    second model per make. 10 slots, never padded. Preserves rank order."""
    picked, picked_ids = [], set()
    seen_pass1, seen_pass2 = set(), set()
    for m in band_models:
        make = m['row'].make
        key = m['row'].version_id
        if make not in seen_pass1:
            seen_pass1.add(make)
            picked.append(m)
            picked_ids.add(key)
        if len(picked) == limit:
            return picked
    for m in band_models:
        make = m['row'].make
        key = m['row'].version_id
        if key in picked_ids or make in seen_pass2:
            continue
        seen_pass2.add(make)
        picked.append(m)
        picked_ids.add(key)
        if len(picked) == limit:
            break
    return picked


def matches_header(total, shown):
    """List header strings (section 7). None when the band is empty."""
    if total == 0:
        return None
    if total == 1:
        return 'Showing 1 match'
    if shown >= total:
        return f'Showing all {total} matches'
    return f'Showing {shown} of {total} matches'


# --- Current car costing (section 8) ----------------------------------------

GVG_COSTING_BASIS = "Estimated from your car's fuel use and class averages."

# Fixed-cost parts rebuilt from class medians of the Mode B rows.
GVG_FIXED_PARTS = ('ctp', 'comprehensive', 'registration', 'servicing', 'tyres',
                   'road_user_charge')


def cost_gvg_current_vehicle(record, state, annual_km=None):
    """Pure Cost COO p.a. (integer cents) for a Green Vehicle Guide current car.

    Fixed costs are class medians rebuilt from the Mode B dial rows, by class
    and state; fuel/electricity is the car's own GVG consumption through the
    standard cost formulas, at its class kilometres and the state's prices.

    ``annual_km`` overrides the class benchmark — the current-vehicle path
    passes a figure derived from the owner's odometer and purchase date (B-02)
    so the card reflects the real car, not the class average.
    """
    from apps.vehicles.models import (
        CategoryAnnualKMBenchmark,
        CoreDialBatch,
        CoreDialRow,
        StateEnergyPrice,
    )

    state = (state or '').upper()
    batch = CoreDialBatch.objects.filter(is_current=True).first()
    rows = list(CoreDialRow.objects.filter(
        batch=batch, state=state,
        fcai_category__iexact=(record.fcai_category or ''),
    )) if batch else []

    parts = {}
    for part in GVG_FIXED_PARTS:
        field = f'{part}_cents'
        values = [getattr(r, field) for r in rows]
        parts[part] = int(round_half_up(statistics.median(values), 0)) if values else 0

    km = annual_km or CategoryAnnualKMBenchmark.get_annual_km_for_category(
        record.fcai_category or '')
    prices = StateEnergyPrice.get_price_for_state(state)
    parts['fuel'] = 0
    parts['electricity'] = 0
    powertrain = (record.powertrain_type or '').lower()

    def _median_cents(field, scale_km=False):
        # Only rows that actually incur this cost — BEVs have fuel_cents=0 and
        # petrol cars electricity_cents=0, which would corrupt the median.
        values = [getattr(r, field) for r in rows if getattr(r, field)]
        if not values:
            return 0
        median = int(round_half_up(statistics.median(values), 0))
        if scale_km and annual_km:
            # The dial rows were costed at the class benchmark km, so a
            # km override has to rescale the median to stay consistent
            # with the consumption-based branch above.
            benchmark_km = CategoryAnnualKMBenchmark.get_annual_km_for_category(
                record.fcai_category or '')
            if benchmark_km:
                median = int(round_half_up(median * annual_km / benchmark_km, 0))
        return median

    if powertrain == 'bev':
        wh_per_km = getattr(record, 'electricity_consumption_wh_per_km', None)
        rate = getattr(prices, 'electricity_cents_per_kwh', None) if prices else None
        if wh_per_km and rate:
            parts['electricity'] = int(round_half_up(wh_per_km * km / 1000 * rate, 0))
        if not parts['electricity']:
            # Consumption unknown (e.g. AI-searched car): fall back to the
            # class median energy cost from the dial rows.
            parts['electricity'] = _median_cents('electricity_cents', scale_km=True)
    else:
        consumption = getattr(record, 'fuel_consumption_combined_l_100km', None)
        if consumption and prices:
            price = (prices.diesel_cents_per_litre if powertrain == 'diesel'
                     else prices.petrol_ulp95_cents_per_litre)
            if price:
                parts['fuel'] = int(round_half_up(consumption / 100 * km * price, 0))
        if not parts['fuel']:
            # Consumption unknown (e.g. AI-searched car): fall back to the
            # class median fuel cost from the dial rows.
            parts['fuel'] = _median_cents('fuel_cents', scale_km=True)

    # Resale: prefer the record's own stored estimate; only derive one from
    # the retention formula when the record carries none (GVG rows never do).
    resale = getattr(record, 'resale_value_5yr_estimate', None)
    if not resale:
        driveaway = getattr(record, 'driveaway_price_estimate', None)
        if driveaway and getattr(record, 'year', None):
            from apps.mygarage.ai_service import estimate_resale_value
            resale = estimate_resale_value(
                driveaway, record.year,
                powertrain_type=getattr(record, 'powertrain_type', None),
                brand=getattr(record, 'make', None) or getattr(record, 'brand', None))

    return {
        'core_rating': None,
        'band_name': '',
        'band_slug': '',
        'total_annual_cost': sum(parts.values()),
        'annual_cost_breakdown': _gvg_breakdown_shape(parts),
        'tailpipe_co2_g_per_km': float(getattr(record, 'tailpipe_co2_g_per_km', None) or 0),
        'annual_co2_kg': _annual_co2_kg(record, km, state),
        'annual_km': km,
        'costing_basis': GVG_COSTING_BASIS,
        'is_estimate': True,
        'resale_value_5yr_estimate': resale,
    }


def _gvg_breakdown_shape(parts: dict) -> dict:
    """GVG parts keyed like the catalogue breakdown so the frontend can
    consume both identically; the legacy part names are kept alongside."""
    breakdown = dict(parts)
    total = sum(parts.values())
    breakdown.update({
        'fuel_or_energy_annual': parts.get('fuel', 0) + parts.get('electricity', 0),
        'insurance_annual': parts.get('comprehensive', 0),
        'ctp_annual': parts.get('ctp', 0),
        'registration_annual': parts.get('registration', 0),
        'servicing_annual': parts.get('servicing', 0),
        'tyres_annual': parts.get('tyres', 0),
        'ev_levy_annual': parts.get('road_user_charge', 0),
        'other_annual': 0,
        'finance_annual': 0,
        'resale_credit_annual': 0,
        'total_annual': total,
    })
    return breakdown


def _annual_co2_kg(record, km: int, state: str = None) -> int:
    """Energy-cycle annual CO2 (kg).

    Combustion cars report tailpipe emissions (the Guide's published basis).
    BEVs have no tailpipe figure — report energy-cycle instead (grid scope 2
    + scope 3 from the same NGA factors the v6.4 sheets use) so an EV never
    renders "~0 kg" (B-04).
    """
    powertrain = (getattr(record, 'powertrain_type', None) or '').lower()
    tailpipe = getattr(record, 'tailpipe_co2_g_per_km', None) or 0

    if powertrain == 'bev':
        wh_per_km = getattr(record, 'electricity_consumption_wh_per_km', None)
        if wh_per_km and km:
            from apps.vehicles.models import NGAEmissionFactor
            from apps.vehicles.services.uncosted_estimates import (
                GRID_REGION, GRID_SCOPE3)
            grid = GRID_REGION.get(state, state) if state else 'National'
            nga = (NGAEmissionFactor.objects.filter(grid=grid).first()
                   or NGAEmissionFactor.objects.filter(grid='National').first())
            s2 = float(nga.scope2_factor_kgco2e_per_kwh) if nga else 0.59
            s3 = GRID_SCOPE3.get(grid, GRID_SCOPE3['National'])
            # kg/kWh is numerically g/Wh, so Wh/km x (s2+s3) is g/km.
            g_per_km = wh_per_km * (s2 + s3)
            return int(round_half_up(g_per_km * km / 1000, 0))
        return 0

    if not tailpipe:
        return 0
    return int(round_half_up(tailpipe * km / 1000, 0))


# Minimum ownership history before annualising an odometer reading: under
# ~3 months the rate extrapolates to noise.
MIN_OWNERSHIP_YEARS = 0.25
# Guard rails for annualised odometer rates (km/yr). Within this range the
# owner's real usage is trusted; outside it the class benchmark wins —
# an absurd rate nearly always means a wrong purchase date.
KM_RATE_FLOOR = 3_000
KM_RATE_CEIL = 60_000


def annual_km_from_odometer(odometer_reading, purchase_date, today=None):
    """Annualised km from the owner's odometer + purchase date (B-02).

    Returns None when the inputs can't produce a trustworthy rate (missing
    either value, purchase date in the future, under 3 months of ownership,
    or a rate outside the guard rails) — callers fall back to the class
    benchmark.
    """
    if not odometer_reading or not purchase_date:
        return None
    from datetime import date
    today = today or date.today()
    days = (today - purchase_date).days
    if days <= 0:
        return None
    years = days / 365.25
    if years < MIN_OWNERSHIP_YEARS:
        return None
    rate = round(odometer_reading / years / 100) * 100
    if rate < KM_RATE_FLOOR or rate > KM_RATE_CEIL:
        return None
    return rate
