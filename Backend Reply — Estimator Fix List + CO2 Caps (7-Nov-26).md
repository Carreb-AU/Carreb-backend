# Backend Reply — Homepage Cost Estimator Fix List + CO₂ Caps (7-Nov-26)

**To:** Jock · **From:** Ali (backend)
**Environment:** `api.carreb.com.au`, commit `a931b08` (estimator) + `487178e` (caps), both live.
**Tests:** estimator suite 12/12 green; full vehicles suite green.

---

## Part 1 — Homepage cost estimator (`/api/vehicles/estimate-cost/`)

Your seven-item fix list, item by item. Everything is deployed and the §7 check was run against production.

### 1) Data source — DONE
The estimator read `VehicleCOOComponentBreakdown`, which `sync_sheet_24` had loaded from the July workbook ("Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx", COO_Component_Breakdown tab — 771 vehicles: petrol 547 / diesel 128 / EV 96 / hybrid 9). It now aggregates the **same source the live vehicle pages use** — the current CORE Dial batch: live rows of the 04-Nov FINAL LAUNCH only, `is_suppressed` listings never enter it, Pure Cost (Mode B) components, one row per vehicle per state. No reload of the old table needed; it is simply no longer read by this endpoint.

### 2) Fuel types — DONE
Filtering is on the dataset fuel-type field (`energy_norm`) only — never on "hybrid" in model/variant names. Accepted values: `petrol`, `diesel`, `hybrid` (**HEV only**), `mild_hybrid`, `phev`, `electric`/`ev`. PHEV (147) and mild hybrid (226) are separate types, never lumped into hybrid. Unknown values return **400** `{"status":"error","message":"Unknown fuel_type '…'. Expected one of: petrol, diesel, hybrid, mild_hybrid, phev, electric."}` — the silent petrol fallback is removed.

### 3) Grocery number — DONE
`GROCERY_WEEKLY_BASELINE = 207` with the comment "Average household grocery spend, Finder Consumer Sentiment Tracker, March 2026". Weeks = `floor(saving / 207 + 0.5)` — half-up, not Python's banker's `round()`. If weeks = 0, or the saving is zero or negative, `grocery_comparison_text` is `""`.

### 4) Grocery wording — DONE
Both branches (EV and non-EV): **"That potential estimated saving is about the same as {X} weeks of the average household grocery shop."** — singular "week" when X = 1. The saving basis is unchanged: against EV for every fuel type; against petrol when EV is selected.

### 5) Negative results — DONE
The `max(0.0, …)` clamps are removed from both `potential_saving_vs_ev` and `potential_saving_vs_petrol` — the fields are now signed. When the selected type costs more, `summary_disclaimer` ends **"Estimated extra cost against EV: ~$X/yr"** (or "against petrol" for EV) and there is no grocery line.

### 6) Tests — DONE
`tests/test_cost_estimator.py` updated: the old text asserts and the PHEV→"hybrid" assert replaced; new coverage for the 400 on unknown fuel, the mhev/phev buckets, half-up week rounding, and the negative-savings disclaimer. 12/12 green.

### 7) Check — RUN, results below
`GET /api/vehicles/estimate-cost/?fuel_type=X&annual_km=10000&state=NSW` against production:

| fuel_type | sample_size | running cost | saving | grocery text |
|---|---|---|---|---|
| petrol | **499** | $5,393/yr | $881/yr | "…about the same as 4 weeks of the average household grocery shop." |
| diesel | **284** | $5,936/yr | $1,424/yr | "…7 weeks…" |
| electric | **308** | $4,512/yr | $881/yr (vs petrol) | "…4 weeks…" |
| hybrid (HEV) | **172** | $4,448/yr | **−$64/yr** | *(empty — extra cost case)* |
| mild_hybrid | **226** | $5,514/yr | $1,002/yr | "…5 weeks…" |
| phev | **147** | $5,067/yr | $555/yr | "…3 weeks…" |

All six NSW sample sizes match your expected 04-Nov counts exactly (499 / 284 / 308 / 172 / 226 / 147). The hybrid row demonstrates §5 live: its disclaimer reads *"…Individual costs vary significantly · Estimated extra cost against EV: ~$64/yr"* and the grocery line is empty. Sanity note: a full HEV undercutting the EV average on running cost at 10,000 km is plausible on this data (HEVs carry no EV levy and less insurance than the BEV average) — the figures are the honest dataset output, not a bug.

---

## Part 2 — CORE™ CO₂ caps: confirmed, and fixed

**Your question:** do the caps run on the energy-cycle figure, not tailpipe?

**What we found:** two of the three cap paths were stale — the dial import read the **tailpipe** column and applied the **old 250/200/150** thresholds; the rating engine capped on `tailpipe_co2_g_per_km` with the same old cutoffs. (The FAQ was faithfully describing the code.) The third path (uncosted estimates) already had the right rule.

**What the dataset says:** the workbook's own `co2_cap_tier` column is computed on the **energy-cycle** figure with thresholds **190 / 250 / 315 g/km → caps 4.4 / 3.4 / 2.4** (the 21-Oct re-basing, Policy Update Log #56, your approval), and **BEV/FCEV are never capped** ("none (BEV/FCEV)").

**Fix:** all paths now match the dataset exactly — energy-cycle g/km, ≥315 → 2.4, 250–314 → 3.4, 190–249 → 4.4, <190 → no cap, BEV/FCEV exempt. The dial was rebuilt (13,120 rows). Verified tier-for-tier against the workbook:

| vehicle | energy-cycle g/km | dataset tier | our dial now |
|---|---|---|---|
| Aston Martin DB12 | 353.8 | ≥315 → 2.4 | **2.4** ✓ |
| Audi Q7 TFSI | 269.7 | 250–314 → 3.4 | **3.4** ✓ |
| Audi Q7 TDI | 237.3 | 190–249 → 4.4 | **4.4** ✓ |
| Alfa Romeo Giulia Quadrifoglio | 237.8 | 190–249 → 4.4 | **4.4** ✓ |

**FAQ update (your side):** the correct public wording is — *"CO₂ caps apply to the energy-cycle emissions figure (including fuel and electricity production) at 190 / 250 / 315 g/km; battery-electric and hydrogen vehicles are exempt."* The old "250/200/150 tailpipe" line should be replaced; the BEV-exempt statement was and remains correct.

---

*Commits: `487178e` (caps + estimator data source), `a931b08` (fix list items 2–6). Anything here that doesn't match the API is a backend bug — send the curl + response.*
