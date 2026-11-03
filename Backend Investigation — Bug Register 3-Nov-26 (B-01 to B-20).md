# Backend Investigation — Carreb v6.4 Launch Bug Register (3-Nov-26)

**Date:** 3 Nov 2026 · **Scope:** B-01 … B-20 · **Method:** code review + live production verification (prod DB via Django shell; frontend repo read-only)

Verdicts: **[BE]** backend issue exists today · **[BE-FIXED]** already fixed before this register · **[FE]** frontend/copy only · **[NBE]** not a backend defect (backend proven correct)

---

## Confirmed backend issues

### B-01 — GVG model-year (MYxx) not searchable — **[BE]**
`VehicleIdentity` has no model-year/MY field (only `year`). GVG rows store the MY label in `raw_data` but not in a queryable column. Live proof: ZEEKR 009 is stored as `year=2024` only; searching "zeekr 009 2025" finds nothing and falls through to AI. The register cites 352 GVG rows where the MY label ≠ release year.
**Fix:** importer writes a `model_year`/MY column; search matches on it.

### B-02 — Odometer / purchase date ignored for GVG/AI current vehicle — **[BE]**
`cost_gvg_current_vehicle` (`apps/vehicles/services/core_dial.py:230`) sets annual km from `CategoryAnnualKMBenchmark` only. Odometer and purchase date stored on `CurrentVehicle` are never used, so the km figure never reflects the real car.
**Fix:** derive annual km from (odometer − delivery km) ÷ years owned, fall back to benchmark.

### B-04 — EV CO₂ shows ~0 — **[BE]**
`_annual_co2_kg` (`core_dial.py:338`) is tailpipe-only; BEVs return 0. Catalogue cards are fine (energy-cycle via rating engine) but the GVG/AI current-vehicle path has no energy-cycle calculation. Live: the AI 009 CV card returns `annual_co2_kg=0`.
**Fix:** energy-cycle CO₂ for GVG/AI records using `co2_energy_cycle_g_per_km` where available, or fuel/electricity production factors.

### B-12 — Held (suppressed) listings appear in matches/bands/garage — **[BE]**
`Vehicle.is_suppressed` **is** imported (314 suppressed rows on prod, set when every listing in a name group is held) but **no view, selector or service filters on it**. Held rows can appear in Smart Match results, CORE Dial bands and garage cards. Also 138 unpriced vehicles (Sprinter, Continental GT, Vito, Crafter, Iveco, most Aston Martins) carry no price anywhere from the 2-Nov fill skip list.
**Fix:** `is_suppressed=False` on every catalogue queryset ( VehicleListView, AISmartMatchView, CoreDialRows import, free-match selectors, garage card builder).

### B-13 — Est. Cost Difference mixes CORE modes — **[BE]**
Garage cards subtract the current vehicle's **Pure Cost** baseline from a card costed in the user's selected mode. Live: Vantage card (Value Later, $48,241/yr) minus CV Pure Cost baseline ($5,991/yr) = "more_expensive $42,250" — apples to oranges.
**Fix:** cost the CV in all four modes (catalogue rows already store per-mode `mode_data_by_state`) and subtract same-mode.

### B-14 — Smart Car Finder relaxation — **[BE] partial**
Free-match wizard (`apps/freematch/services.py:117`): when the strict query returns nothing, the budget constraint is **dropped entirely** (both directions) rather than relaxed **downward only** as the register expects. Ordering is CORE rating, then annual cost — so with equal ratings the **cheapest** car (furthest below a high budget) sorts first. The "matches based on what you told us" copy is FE, but BE must: relax downward only and/or order by budget proximity, and expose which constraints were relaxed (the response already has `is_suggested`; FE must show it).

### B-15 — CORE badge arcs not data-driven — **[BE]**
`CategoryScoringBounds` (cat_min/max_coo, cat_min/max_co2 per category × mode) **is in the database** and used internally by the rating engine — but **no API payload exposes it**, so the frontend has nothing to compute arc positions from and draws both arcs at fixed lengths. Per Decision E (3-Nov): needle = (value − min) / (max − min), clamped 0–1.
**Fix:** add `cost_arc`/`co2_arc` blocks (value + min + max, or precomputed needle fractions) to the card payload, keyed by mode and state.

### B-16 — RideReveal content guard — **[BE]**
`generate_ridereveal_content` (`apps/mygarage/tasks.py`) validates only that six fields exist. Nothing checks the banned list (research claims, purchase advice, third person, emissions claims) — compliance is prompt-only, and the register shows GPT-4o-mini produced "Research indicates…" and purchase-advice wording anyway. The disclaimer **is** stored on the result and serialized (`serializers.py:191`); whether it renders is FE.
**Fix:** programmatic post-generation guard (regex/LLM check) with one retry, then fail/refund credit.

### B-17 — RideReveal headline / plate & colour editing — **[BE]**
The system prompt never demands second person ("you"), so output comes back third-person ("individuals choosing hybrid vehicles…"). `first_name` is persisted (commit ff2c902). There is **no edit path**: `trigger_ridereveal_generation` returns the existing result unchanged, ignoring any new `custom_plate`/`favorite_color`.
**Fix:** enforce second person in prompt + guard; add regenerate-with-edits (or update fields on the existing result).

### B-18 — Same five trait pills on every card — **[BE]**
`RideRevealResult` has **no traits field at all** — nothing is generated, stored or served. The frontend renders a hardcoded fallback array (`RIDE_REVEAL_FALLBACK_TRAITS` in `rideRevealProfile.js`, marked "Temporary design fallback until the result API includes personality traits"). This is not "unmerged work" — the backend capability simply doesn't exist in current code.
**Fix:** add `traits` (5 per card, spec §3.4) to the prompt, result model and serializer.

### B-20 — Filter-search cards: CORE™ 0.0 with five stars — **[BE]**
Search/lookup surfaces return the canonical card (`CARD_FIELDS` in `vehicle_card.py`) which contains **no per-mode rating or star keys**. The modal therefore renders 0.0 and falls back to five default stars. The LandCruiser prices the register quotes ($150,580 / $107,296) are the **NSW** column of the *current* 29-Oct load — the same state-mismatch family as B-11, not an older dataset.
**Fix:** include `core_rating_1dp` + `stars` for the user's selected mode and state in search/lookup responses.

---

## Already fixed before the register

### B-03 — "$297 resale on every car" — **[BE-FIXED]**
Fixed in the 2-Nov work: CV cards now derive resale from the resolved driveaway price via the retention formula (the 009 CV card currently shows resale $73,623 off $147,247). No near-zero-base resale is emitted any more.

### B-08 — Hero "save up to $64,151/yr" — **[BE-FIXED via B-13] + Copy**
`SavingsSummaryView` returns max band difference in per-year cents — the math unit was always correct. The impossible figure was a symptom of the broken CV baseline (B-02/B-13). Once B-13 lands, the number becomes a real per-year difference. "Save up to" wording, doubled "Est.", and naming the baseline are FE/Copy per the register's own action split.

---

## Not backend issues

### B-05 — "972 km range" — **[NBE]**
No `972` constant exists anywhere in backend code; the workbook carries 972 only as genuine Nissan Patrol values. Vantage catalogue card returns `range_total_km=695` (tank 73 L, consumption blank in the workbook → no derived range). What the register saw was frontend/stale rendering, not a backend value.

### B-07 / B-09 / B-10 / B-19 — **[FE]** (wording, CO₂ basis label, silhouette nearest-year lookup, Category-Avg toggle hidden per Decision)

### B-11 — "My Matches cards don't reproduce the 29-Oct dataset" — **[NBE] — root cause found**
The site was running the 29-Oct load all along; **there is only one CoreDialBatch** (`v6.4-audit-29Oct26`) and the DB matches the file to the dollar **for the state actually in play**. The register's "wrong" figures are the **NT column**:
- GAC M8 Luxury: NT $85,221 (register) vs QLD $86,135 (file)
- Sealion 8 Dynamic FWD: NT $57,823 vs QLD $59,003
- Kia Sorento S Hybrid FWD: NT $59,180 vs QLD $58,637

Cause: the test account's current vehicle (AI "2025 Zeekr 009") is registered **state=NT**, so Smart Match, garage cards and the Dial all correctly priced in NT. The cards were then compared against QLD file columns. The "Est. Driveaway Price · QLD" caption is **hardcoded** in `CarDealCard.js:247` — a frontend bug that made NT values look like QLD ones. Same story for B-20's NSW prices (that path defaults to NSW).
Real sub-items: held Vantage visible (→ B-12), ZEEKR "2025" label (→ B-01), star count rendered as rating (FE).

---

## Summary table

| Bug | Verdict | Owner |
|---|---|---|
| B-01 GVG MYxx | BE exists | BE |
| B-02 odometer/purchase date | BE exists | BE |
| B-03 $297 resale | **Fixed 2-Nov** | — |
| B-04 EV CO₂ ~0 | BE exists | BE |
| B-05 972 km | Not backend | FE/stale |
| B-06 not like-for-like | Derivative of B-02/04/13 | BE |
| B-07 wording | FE/Copy | FE |
| B-08 hero figure | Fixed via B-13; copy FE | BE+FE |
| B-09 CO₂ basis label | FE | FE |
| B-10 silhouette | FE | FE |
| B-11 dataset mismatch | **State mismatch (NT), hardcoded QLD label** | FE label |
| B-12 held listings shown | BE exists | BE |
| B-13 mode-mixed diff | BE exists | BE |
| B-14 finder relaxation | BE partial (downward-only + ordering) | BE+FE |
| B-15 badge arcs | BE gap (bounds not exposed) | BE+FE |
| B-16 RR guard | BE exists | BE |
| B-17 RR headline/edit | BE exists | BE+FE |
| B-18 RR traits | BE gap (feature missing) | BE |
| B-19 toggle | FE per Decision | FE |
| B-20 0.0/five stars | BE gap (no rating keys) | BE+FE |

**Backend fix list (priority order):** B-12 (one-line filter, launch-critical) → B-13 → B-02 → B-04 → B-20/B-15 (payload additions) → B-14 → B-16/B-17/B-18 → B-01 (importer + search).
