"""Parser that turns the "Consolidated Vehicles v6.4" workbook sheet into
CORE Dial rows (Mode B / Pure Cost only).

Sheet layout (verified against the 07-Oct-26 and 13-Oct-26 workbooks):
  * rows sorted by (Make, Model, Variant, Year) — a "name group";
  * a name group holds one or more listings; each listing has exactly
    8 states × 4 modes = 32 rows;
  * within a name group, consecutive rows form state runs (state changes =>
    new run); each run holds N quads of 4 rows (modes B, E, C, F) — one quad
    per listing — and the quads of a given state are in listing order.

So: split each state run into quads at every 'B' row; quad k of every state
belongs to listing k. version_id is the catalogue order (first appearance,
1..N). model_id is the first 12 hex of SHA-256("year|make|model").

National scores (D30): price_score / emissions_score are the medians of the
listing's per-state Mode B scores, rounded half-up to 6 dp, and are copied
onto every state row.
"""
import hashlib
import logging
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import openpyxl

from apps.vehicles.services.core_dial import AU_STATES

logger = logging.getLogger(__name__)

SHEET_NAME = 'Consolidated Vehicles v6.4'

# Research Status values that count as "on sale" (section 2)
ON_SALE_STATUSES = ('v6.3.4 seed', 'Confirmed')

# 0-based column indexes (col letters per spec: Q=16, W=22, Y=24, Z=25, AA=26,
# AO..AV = 40..47; A..D = 0..3, M = 12, N = 13, O = 14, U = 20, AE = 30,
# AH = 33)
COL_MAKE, COL_MODEL, COL_VARIANT, COL_YEAR = 0, 1, 2, 3
COL_FUEL = 4
COL_CO2_GKM = 12
COL_STATE = 13
COL_FCAI = 14
COL_DRIVEAWAY = 16
COL_MODE = 20
COL_MODE_COO = 22
COL_CO2_KG = 24
COL_PRICE_SCORE = 25
COL_EMISSIONS_SCORE = 26
COL_SCORING_VERSION = 30
COL_RESEARCH_STATUS = 33
COL_PRICE_BASIS = 67  # BP 'price_basis' in the 13-Oct layout; optional
PART_COLS = {
    'fuel': 40,
    'electricity': 41,
    'ctp': 42,
    'comprehensive': 43,
    'registration': 44,
    'servicing': 45,
    'tyres': 46,
    'road_user_charge': 47,
}

PART_KEYS = tuple(PART_COLS.keys())


@dataclass
class ParsedListing:
    """One catalogue listing: a named variant with 8 states × 4 mode rows."""
    make: str
    model: str
    variant: str
    year: int
    research_status: str
    states: Dict[str, dict]  # state -> {'B': row, 'E': row, 'C': row, 'F': row}


@dataclass
class DialRowData:
    """A CoreDialRow not yet written to the database."""
    version_id: int
    model_id: str
    make: str
    model: str
    variant: str
    year: int
    fcai_category: str
    state: str
    driveaway_cents: int
    coo_pa_cents: int
    annual_co2_kg: float
    co2_g_per_km: float
    price_score: float
    emissions_score: float
    co2_cap: Optional[float]
    parts_cents: Dict[str, int]
    price_basis: str = ''


@dataclass
class ParsedWorkbook:
    scoring_version: str
    as_at: Optional[str]
    listings: List[ParsedListing] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)

    def dial_rows(self):
        """Flatten to dial row data for on-sale listings, all states."""
        from apps.vehicles.services.core_dial import (
            co2_cap_for, dollars_to_cents, round_half_up,
        )

        rows: List[DialRowData] = []
        for version_id, listing in enumerate(self.listings, start=1):
            if listing.research_status not in ON_SALE_STATUSES:
                continue
            # National scores: median of per-state Mode B scores, 6 dp (D30)
            price_scores, emissions_scores = [], []
            for st in AU_STATES:
                b = listing.states[st]['B']
                if isinstance(b[COL_PRICE_SCORE], (int, float)):
                    price_scores.append(b[COL_PRICE_SCORE])
                if isinstance(b[COL_EMISSIONS_SCORE], (int, float)):
                    emissions_scores.append(b[COL_EMISSIONS_SCORE])
            if not price_scores or not emissions_scores:
                self.problems.append(
                    f"{listing.make} {listing.model} {listing.variant} {listing.year}: "
                    "missing per-state scores; skipped"
                )
                continue
            nat_price = round_half_up(statistics.median(price_scores), 6)
            nat_emissions = round_half_up(statistics.median(emissions_scores), 6)

            act_b = listing.states['ACT']['B']
            co2_g_per_km = float(act_b[COL_CO2_GKM] or 0)
            co2_cap = co2_cap_for(str(act_b[COL_FUEL]).lower(), co2_g_per_km)
            model_id = hashlib.sha256(
                f"{listing.year}|{listing.make}|{listing.model}".encode('utf-8')
            ).hexdigest()[:12]

            for st in AU_STATES:
                b = listing.states[st]['B']
                parts_cents = {}
                for key, idx in PART_COLS.items():
                    raw = b[idx]
                    parts_cents[key] = dollars_to_cents(raw) if isinstance(raw, (int, float)) else 0
                coo_cents = dollars_to_cents(b[COL_MODE_COO])
                parts_sum = sum(parts_cents.values())
                if parts_sum != coo_cents:
                    self.problems.append(
                        f"{listing.make} {listing.model} {listing.variant} "
                        f"{listing.year} {st}: Mode B COO {coo_cents}c != sum of "
                        f"parts {parts_sum}c"
                    )
                rows.append(DialRowData(
                    version_id=version_id,
                    model_id=model_id,
                    make=listing.make,
                    model=listing.model,
                    variant=listing.variant,
                    year=listing.year,
                    fcai_category=str(b[COL_FCAI] or ''),
                    state=st,
                    driveaway_cents=dollars_to_cents(b[COL_DRIVEAWAY]),
                    coo_pa_cents=coo_cents,
                    annual_co2_kg=float(b[COL_CO2_KG] or 0),
                    co2_g_per_km=co2_g_per_km,
                    price_score=nat_price,
                    emissions_score=nat_emissions,
                    co2_cap=co2_cap,
                    parts_cents=parts_cents,
                    price_basis=str(b[COL_PRICE_BASIS] or '') if len(b) > COL_PRICE_BASIS else '',
                ))
        return rows


def parse_name_group(name, group_rows, problems) -> List[ParsedListing]:
    """Split one name group's rows into listings (see module docstring)."""
    make, model, variant, year = name
    # Split into state runs; each run holds N quads (B,E,C,F), one per listing.
    per_state: Dict[str, list] = {}
    order: List[str] = []
    for i, row in enumerate(group_rows):
        if row[COL_MODE] == 'B':
            state = row[COL_STATE]
            if state not in per_state:
                order.append(state)
            per_state.setdefault(state, []).append(group_rows[i:i + 4])

    missing = [st for st in AU_STATES if st not in per_state]
    if missing:
        problems.append(f"{make} {model} {variant} {year}: missing states {missing}")
        return []

    quad_counts = {len(quads) for quads in per_state.values()}
    if len(quad_counts) != 1:
        problems.append(f"{make} {model} {variant} {year}: uneven state runs")
        return []
    n_listings = quad_counts.pop()

    listings = []
    for k in range(n_listings):
        states = {}
        ok = True
        for st in AU_STATES:
            quad = per_state[st][k]
            if len(quad) != 4 or [r[COL_MODE] for r in quad] != ['B', 'E', 'C', 'F']:
                problems.append(
                    f"{make} {model} {variant} {year} {st} listing {k + 1}: "
                    "malformed mode quad"
                )
                ok = False
                break
            states[st] = {r[COL_MODE]: r for r in quad}
        if not ok:
            continue
        research = {states[st]['B'][COL_RESEARCH_STATUS] for st in AU_STATES}
        if len(research) != 1:
            problems.append(f"{make} {model} {variant} {year}: mixed research status")
            continue
        listings.append(ParsedListing(
            make=make, model=model, variant=variant, year=year,
            research_status=research.pop(),
            states=states,
        ))
    return listings


def parse_workbook(path, as_at: Optional[str] = None) -> ParsedWorkbook:
    """Parse the Consolidated Vehicles v6.4 sheet of the given workbook."""
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        ws = wb[SHEET_NAME]
        name_groups: Dict[tuple, list] = {}
        group_order: List[tuple] = []
        scoring_versions = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[COL_MAKE] is None:
                continue
            name = (row[COL_MAKE], row[COL_MODEL], row[COL_VARIANT], row[COL_YEAR])
            if name not in name_groups:
                name_groups[name] = []
                group_order.append(name)
            name_groups[name].append(row)
            sv = row[COL_SCORING_VERSION]
            if sv and sv not in scoring_versions:
                scoring_versions.append(sv)
    finally:
        wb.close()

    problems: List[str] = []
    listings: List[ParsedListing] = []
    for name in group_order:
        listings.extend(parse_name_group(name, name_groups[name], problems))

    if not scoring_versions:
        problems.append('No scoring_version found in sheet')
        scoring_version = 'unknown'
    else:
        scoring_version = scoring_versions[0]
        if len(scoring_versions) > 1:
            problems.append(
                f'Multiple scoring versions in sheet: {scoring_versions}; '
                f'using {scoring_version}'
            )

    return ParsedWorkbook(
        scoring_version=scoring_version,
        as_at=as_at,
        listings=listings,
        problems=problems,
    )
