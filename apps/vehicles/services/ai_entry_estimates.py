"""Fill AIVehicleEntry cost fields with sheet-derived estimates.

AI-searched cars are missing from the catalogue, so Grok leaves the cost
columns (CTP/insurance/registration/servicing/tyres, 5yr totals) null. Those
components are exactly what the data sheets provide per FCAI category and
state (CategoryCostDefault and friends), and the car's own consumption is
already on the entry — so every null cost field can be completed without
spending a single extra AI token.

The fill is idempotent (nulls only) and cheap (a handful of indexed reads),
so it runs both at entry-creation time and lazily whenever an entry is
served with missing data, which backfills rows created before this existed.
"""
import logging

from apps.vehicles.models import (
    CategoryAnnualKMBenchmark,
    CategoryCostDefault,
    StateEnergyPrice,
)
from apps.vehicles.services.core_dial import AU_STATES, round_half_up

logger = logging.getLogger(__name__)


def _own_energy_cost_cents(entry, state, row):
    """Fuel/electricity cost from the car's own consumption at the state's
    prices; falls back to the category default when consumption is unknown."""
    km = CategoryAnnualKMBenchmark.get_annual_km_for_category(
        entry.fcai_category or '')
    prices = StateEnergyPrice.get_price_for_state(state)
    powertrain = (entry.powertrain_type or '').lower()
    fuel = 0
    electricity = 0
    if powertrain == 'bev':
        wh_per_km = entry.electricity_consumption_wh_per_km
        rate = getattr(prices, 'electricity_cents_per_kwh', None) if prices else None
        if wh_per_km and rate:
            electricity = int(round_half_up(wh_per_km * km / 1000 * rate, 0))
        if not electricity and row:
            electricity = row.electricity_cost_pa or 0
    else:
        consumption = entry.fuel_consumption_combined_l_100km
        if consumption and prices:
            price = (prices.diesel_cents_per_litre if powertrain == 'diesel'
                     else prices.petrol_ulp95_cents_per_litre)
            if price:
                fuel = int(round_half_up(consumption / 100 * km * price, 0))
        if not fuel and row:
            fuel = row.fuel_cost_pa or 0
    return fuel, electricity


def fill_ai_entry_estimates(entry, save=True):
    """Populate null cost fields on an AIVehicleEntry from sheet defaults.

    Only fills fields that are currently null/empty, so it is safe to call
    repeatedly. Returns the entry (unsaved unless save=True).
    """
    category = (entry.fcai_category or '').strip()
    rows = {
        r.state: r for r in CategoryCostDefault.objects.filter(
            fcai_category__iexact=category)
    } if category else {}
    any_row = next(iter(rows.values()), None)

    if not entry.ctp_by_state:
        ctp = {
            s: rows[s].ctp_pa for s in AU_STATES if rows.get(s) and rows[s].ctp_pa is not None}
        if ctp:
            entry.ctp_by_state = ctp
    if not entry.insurance_estimate_by_state:
        ins = {
            s: rows[s].comprehensive_pa for s in AU_STATES
            if rows.get(s) and rows[s].comprehensive_pa is not None}
        if ins:
            entry.insurance_estimate_by_state = ins
    if not entry.registration_by_state:
        rego = {
            s: rows[s].registration_pa for s in AU_STATES
            if rows.get(s) and rows[s].registration_pa is not None}
        if rego:
            entry.registration_by_state = rego

    if not entry.total_5yr_cost_of_ownership_by_state:
        totals = {}
        for s in AU_STATES:
            row = rows.get(s)
            if not row:
                continue
            fuel, electricity = _own_energy_cost_cents(entry, s, row)
            annual = sum(c or 0 for c in (
                row.ctp_pa, row.comprehensive_pa, row.registration_pa,
                row.maintenance_pa, row.tyre_cost_pa, fuel, electricity,
                row.ev_levy_pa))
            totals[s] = annual * 5
        if totals:
            entry.total_5yr_cost_of_ownership_by_state = totals

    if entry.servicing_5yr_estimate is None and any_row:
        entry.servicing_5yr_estimate = any_row.servicing_5yr_estimate
    if entry.tyre_replacement_estimate is None and any_row:
        entry.tyre_replacement_estimate = any_row.tyre_replacement_estimate

    if save:
        entry.save(update_fields=[
            'ctp_by_state', 'insurance_estimate_by_state', 'registration_by_state',
            'total_5yr_cost_of_ownership_by_state', 'servicing_5yr_estimate',
            'tyre_replacement_estimate',
        ])
    return entry
