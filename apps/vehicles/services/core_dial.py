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
    5: 'Net Zero Ninja™',
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


def cost_gvg_current_vehicle(record, state):
    """Pure Cost COO p.a. (integer cents) for a Green Vehicle Guide current car.

    Fixed costs are class medians rebuilt from the Mode B dial rows, by class
    and state; fuel/electricity is the car's own GVG consumption through the
    standard cost formulas, at its class kilometres and the state's prices.
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

    km = CategoryAnnualKMBenchmark.get_annual_km_for_category(record.fcai_category or '')
    prices = StateEnergyPrice.get_price_for_state(state)
    parts['fuel'] = 0
    parts['electricity'] = 0
    powertrain = (record.powertrain_type or '').lower()
    if powertrain == 'bev':
        wh_per_km = getattr(record, 'electricity_consumption_wh_per_km', None)
        rate = getattr(prices, 'electricity_cents_per_kwh', None) if prices else None
        if wh_per_km and rate:
            parts['electricity'] = int(round_half_up(wh_per_km * km / 1000 * rate, 0))
    else:
        consumption = getattr(record, 'fuel_consumption_combined_l_100km', None)
        if consumption and prices:
            price = (prices.diesel_cents_per_litre if powertrain == 'diesel'
                     else prices.petrol_ulp95_cents_per_litre)
            if price:
                parts['fuel'] = int(round_half_up(consumption / 100 * km * price, 0))

    return {
        'core_rating': None,
        'band_name': '',
        'band_slug': '',
        'total_annual_cost': sum(parts.values()),
        'annual_cost_breakdown': parts,
        'costing_basis': GVG_COSTING_BASIS,
        'is_estimate': True,
    }
