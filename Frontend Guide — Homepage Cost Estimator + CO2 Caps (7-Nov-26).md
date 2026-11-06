# Frontend Guide — Homepage Cost Estimator + CO₂ Caps (7-Nov-26)

**For:** Meenam / Abdullah · **From:** Ali (backend)
**Companion to:** "Frontend API Guide — COMPLETE Final (7-Nov-26)" — everything there stands; this adds the homepage cost-estimator contract changes. Live on `api.carreb.com.au` (commit `a931b08`).

---

## 1. What changed on `GET /api/vehicles/estimate-cost/`

The endpoint now reads the **current 04-Nov dataset** (live rows only) instead of the July table. Response shape is unchanged — same keys — but the semantics of several fields changed. Render as sent; don't re-derive.

### New/changed query params
- `fuel_type` now accepts six values: **`petrol`, `diesel`, `hybrid` (HEV only), `mild_hybrid`, `phev`, `electric`** (`ev`/`bev` also map to electric). If the homepage fuel picker adds mild-hybrid and PHEV options, pass them straight through.
- **Unknown fuel_type → 400** `{"status":"error","message":"Unknown fuel_type '…'. Expected one of: petrol, diesel, hybrid, mild_hybrid, phev, electric."}` — show this message; the old silent petrol fallback is gone.
- `annual_km`, `state`, `category` unchanged.

### Signed savings — the important one
`potential_saving_vs_ev` and `potential_saving_vs_petrol` are **no longer clamped at 0**. Negative means the selected type costs MORE than the comparison:

- `summary_disclaimer` already carries the right ending — render it verbatim:
  - positive → `…Estimated potential saving against EV: ~$X/yr` (or "against petrol" when `fuel_type: electric`)
  - negative → `…Estimated extra cost against EV: ~$X/yr` (or "against petrol")
- **Do not** display a "$0 saving" for negative values, and do not show a grocery comparison for them (the API sends `grocery_comparison_text: ""` and `equivalent_grocery_weeks: 0`).
- Live example: `fuel_type=hybrid&annual_km=10000` returns saving −$64/yr → disclaimer says *"Estimated extra cost against EV: ~$64/yr"*, grocery text empty. Handle this state (e.g. neutral styling, no green).

### Grocery comparison
- `grocery_weekly_baseline` is now **207** (Finder Consumer Sentiment Tracker, March 2026).
- `grocery_comparison_text` wording: **"That potential estimated saving is about the same as X weeks of the average household grocery shop."** (singular "week" at 1). Render verbatim when non-empty; empty string → hide the line entirely.

### Sample sizes (for the "based on N vehicles" caption, if you show one)
`sample_size` is the count of distinct live listings behind the average — NSW values: petrol 499, diesel 284, electric 308, hybrid 172, mild_hybrid 226, phev 147.

```bash
# Contract check — all six types at 10,000 km
for f in petrol diesel electric hybrid mild_hybrid phev; do
  curl -s "https://api.carreb.com.au/api/vehicles/estimate-cost/?fuel_type=$f&annual_km=10000&state=NSW" \
    | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d['fuel_type'], d['sample_size'], d['estimated_annual_running_cost'], d['grocery_comparison_text'][:60])"
done

# 400 case
curl -s "https://api.carreb.com.au/api/vehicles/estimate-cost/?fuel_type=banana"
```

## 2. CO₂ caps — display note (no FE work, one FAQ line)

CORE™ CO₂ caps now officially run on the **energy-cycle** figure (incl. fuel/electricity production) with thresholds **190 / 250 / 315 g/km**; BEV/FCEV exempt. The card/Dial fields you render (`co2_cap_tier` text, `co2_cap_applied`, caps on ratings) come from the payload as before — nothing to build. If the FAQ mentions "250/200/150 tailpipe", that line is being corrected on the copy side.

---

*Backend contact: Ali. Anything here that doesn't match the API response is a backend bug — send the curl + response.*
