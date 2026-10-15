# PROMPT — Build the CORE Dial (v6.4) correctly, once and for all

You are rebuilding the **CORE Dial** feature of the Carreb web app (Django backend + browser frontend). A previous implementation exists and is **wrong** — do not copy its behaviour. Everything you need is specified below. Where anything you find in the existing code or older specs disagrees with this prompt, **this prompt wins**.

---

## 0 · The six rules that matter most (read before writing any code)

1. **The CORE Dial runs on Pure Cost (Mode B) only — always.** Whatever the CORE Mode selector says, the Dial's band list, counts, needle, top numbers (COO, CO₂), band breakdown, Est. Cost Difference (both sides), and the matches carousel all use **Pure Cost (Mode B)**. The mode selector only drives the car cards (their Est. COO, five-year cost, and card rating). Never read a Mode E/C/F value anywhere in Dial code. (Decision D29)
2. **One rating per vehicle and CORE Mode, the same in every state.** Ratings are national: `price_score` and `emissions_score` are the medians of the vehicle's per-state scores, stored once and copied onto every state row. State rows supply dollars and the budget window, never the rating. (D30)
3. **The browser re-weights; the server never re-scores on a slider move.** Five fixed My Priority stops; each stop re-uses the stored national `price_score` and `emissions_score`. No network request while the user drags the needle, budget, or priority slider. (D28)
4. **Round half up, exactly like Excel ROUND.** Never use Python `round()` or JavaScript `toFixed()` — both get halves wrong. Use: `Math.floor(x * 10 + 0.5 + 1e-9) / 10` (and the equivalent at other precisions).
5. **Money is integer cents in the database and the API.** Never guess units from the size of a number. Convert dollars → cents once at the boundary (×100, half up).
6. **The golden tests must pass before handover.** Acceptance cases are in section 9 below; the implementation must reproduce them to the dollar.

---

## 1 · What the CORE Dial is

A semicircular dial with five bands (star ratings 1–5). The user sets **My Budget** (slider) and **My Priority** (five stops from cost-focused to green-focused). For the band under the needle, the Dial shows: number of matching car **models**, typical annual cost of ownership (COO), typical annual CO₂, and the estimated cost difference versus the user's current car. A green button opens a list of up to 10 matching cars.

Band names (1★ → 5★): **Captain Carbon™ · The Detour™ · Steady Cruiser™ · Smart Move™ · Every Day Legend™**. Names come from config, never from the data.

---

## 2 · Data the browser holds (the Dial dataset)

The Dial works entirely client-side on one dataset fetched per state:

```
GET /api/core-dial/dataset/?state=NSW
```

Returns **every on-sale listing in the user's state**, cut to its **Mode B (Pure Cost)** row, ascending `version_id`. On sale = Research Status "v6.3.4 seed" or "Confirmed" (≈1,173 of 1,202 listings per state; "Coming FY26", "Pending verify", "Future (post-FY26)" are excluded). No vehicle names in this payload — the Dial needs only counts and medians; names arrive via the matches endpoint (section 7).

```ts
DialDataset = {
  scoring_version: string           // batch label, e.g. "v6.4-rebatch-07Oct26..."
  state: 'ACT'|'NSW'|'NT'|'QLD'|'SA'|'TAS'|'VIC'|'WA'
  as_at: string                     // date of assumption files
  rows: DialRow[]                   // ascending version_id
}

DialRow = {
  version_id: int                   // catalogue order, 1..1202 — the last tie-breaker everywhere
  model_id: string                  // first 12 hex of SHA-256("year|make|model"), UTF-8
  driveaway_cents: int              // driveaway price (col Q) × 100
  coo_pa_cents: int                 // Pure Cost COO p.a. (col W, Mode B) × 100; equals sum of parts_cents
  annual_co2_kg: number             // tailpipe CO₂ p.a. (col Y), not rounded
  price_score: number               // national, 6 dp (col Z, Mode B)
  emissions_score: number           // national, 6 dp (col AA)
  co2_cap: 2.4 | 3.4 | 4.4 | null   // null = no cap
  parts_cents: { fuel, electricity, ctp, comprehensive, registration,
                 servicing, tyres, road_user_charge: int }   // cols AO–AV × 100
}
```

Caching: ETag from `scoring_version + state`; `Cache-Control: private`. Fetch on page load and on state change only — **never on a slider move**. Free users get the dataset too (their locked Dial still shows COO and CO₂).

---

## 3 · My Priority — five fixed stops (D28)

| Stop | Pill | W(p) / W(e) | Helper line |
|---|---|---|---|
| 1 (default) | Mostly cost | 0.80 / 0.20 | We'll focus on estimated ownership costs, with some weight on carbon impact. |
| 2 | Leaning cost | 0.65 / 0.35 | We'll weigh estimated ownership costs a little more than carbon impact. |
| 3 | Balanced | 0.50 / 0.50 | We'll balance estimated ownership costs and carbon impact equally. |
| 4 | Leaning green | 0.35 / 0.65 | We'll weigh carbon impact a little more than estimated ownership costs. |
| 5 | Mostly green | 0.20 / 0.80 | We'll focus on carbon impact, with some weight on estimated ownership costs. |

- Slider ends are labelled **My Wallet** and **My Planet**.
- Store the **stop number (1–5), never the weights**. New users default to **stop 1**.
- Each stop re-weights the stored scores with the rating formula (section 5). No server call.

## 4 · My Budget and the price window

- Slider: **$20,000 to $200,000+, in $5,000 steps**.
- **Window:** cars whose `driveaway_cents` are within **$15,000 either side** of the budget, **both ends included**. At $200,000+: every car from **$185,000 up** (no upper bound).
- Range line, exactly as counted:
  - `Cars priced $45,000–$75,000` for a $60,000 budget
  - `Cars priced up to $35,000` when the lower end is $20,000 or less
  - `Cars priced $185,000 and up` at the top
- **Default when nothing is saved:** the state's median on-sale driveaway, rounded to $5,000 (currently $60,000 in every state).

---

## 5 · Rating formula (browser-side re-weighting)

For each in-window version at the user's stop:

```
core          = W(p) × price_score + W(e) × emissions_score
rating_1dp    = roundHalfUp(core × 5, 1)
co2_cap       = 2.4 if g/km ≥ 250; 3.4 if 200–249; 4.4 if 150–199; none below 150
                (battery EVs and hydrogen are never capped)
rating_capped = min(rating_1dp, co2_cap ?? ∞)        // the number on the badge
band          = max(1, roundHalfUp(rating_capped, 0)) // integer 1–5
```

The dataset carries `co2_cap` precomputed, so the browser only needs `min()`.

**Rounding traps (each is a golden test):**
- BYD Atto 3 Extended Range at Balanced rates **4.5 → band 5** (Python `round()` gives 4 — wrong).
- Audi A4 Sedan 35 TFSI at stop 1 rates **2.5 → band 3** (Python gives 2 — wrong).
- Ford Mustang GT Fastback (250 g/km) rates 2.5, **capped to 2.4 → band 2**.

---

## 6 · The Dial computation — one pass, all client-side

Target: **under 300 ms per change on a mid-range phone. Zero server calls** while the needle, budget, or priority slider moves.

### 6.1 Band counts — each model once per band

1. Rate every in-window version at the user's stop (section 5); assign band 1–5.
2. Within each band, rank versions: **rating DESC, then `coo_pa_cents` ASC, then `version_id` ASC**.
3. Keep each model's **top version** (model = `model_id` = year + make + model).
4. The band's count = number of models remaining.

A model whose versions land in two bands counts in **both**, once in each — this keeps the dial count equal to the matches list total.

### 6.2 The top numbers (per band)

- **COO:** median Pure Cost COO (`coo_pa_cents`) of the band's models — the middle one, or the mean of the two middle ones when the count is even.
- **CO₂:** median `annual_co2_kg` of the **same models**, computed **independently** (not the CO₂ of the median-COO car).
- **Est. Cost Difference** = `current car's Pure Cost COO p.a. − band's COO`. Positive = the band's typical car costs less. Show negatives as-is, in the warning colour. **Both sides are Pure Cost, whatever the mode selector says.** No current car → hide the difference entirely (never fall back to a class average).
- **Breakdown pop-up:** the eight `parts_cents` of the middle car by COO (ties by `version_id`), or the mean of the two middle cars when even. The parts must add up to the COO shown.
- Display: **whole dollars and whole kilograms, half up**. An empty band shows **"—"** in every box.
- Captions: `Estimates for the typical [band]™ car in your budget · Pure Cost basis`. Under Est. Cost Difference: `from your [year make model]`.

### 6.3 The needle (D31)

- **On opening:** sits on the **highest band (most stars) with at least one model**. If every band is empty, it sits on Steady Cruiser™ (band 3) and every number shows "—".
- **After that, only the user moves it.** A budget, stop, or current-car change **never** moves it. If its band empties, it stays put and the green button greys out.

### 6.4 Reference pseudocode (the exact algorithm)

```ts
function roundHalfUp(x: number, dp: number): number {
  const f = 10 ** dp
  return Math.floor(x * f + 0.5 + 1e-9) / f
}

onChange(budget, stop):            // < 300 ms, no server call
  lo = budget - 15000; hi = budget + 15000
  if (budget >= 200000) { lo = 185000; hi = Infinity }
  rows = dataset.rows.filter(v => lo*100 <= v.driveaway_cents && v.driveaway_cents <= hi*100)

  for (const v of rows) {
    const core  = WP[stop] * v.price_score + WE[stop] * v.emissions_score
    v.rating    = Math.min(roundHalfUp(core * 5, 1), v.co2_cap ?? Infinity)
    v.band      = Math.max(1, roundHalfUp(v.rating, 0))
  }

  for (band of 1..5) {
    ranked  = rows.filter(v => v.band === band)
                  .sort(by rating desc, coo_pa_cents asc, version_id asc)
    models  = first row of each model_id in ranked
    count[band] = models.length
    coo[band]   = median(models.coo_pa_cents)          // mean of middle two if even
    co2[band]   = median(models.annual_co2_kg)         // computed independently
    diff[band]  = currentCar ? currentCar.cooPaCents - coo[band] : null
  }

  // first render only:
  needle = highest band with count > 0, else 3
```

---

## 7 · The green button — "View [band]™ vehicles"

Built on the **server** (paid plans only):

```
GET /api/core-dial-matches/?state=NSW&budget=60000&stop=1&band=5&v=<scoring_version>
```

All five params required. **No `mode`, `weight_price` or `weight_emissions` params exist** — the stop number is sent, not float weights, so client and server never round apart.

Server logic (a pure function over the same rows the dataset serves):

1. Apply the window (section 4), ratings (section 5), ranking and one-version-per-model collapse (section 6.1).
2. Fill pass 1: one model per make. Fill pass 2: a second model per make. **10 slots, never padded.**
3. Response:

```ts
DialMatches = {
  scoring_version: string
  total: int            // the band's model count — MUST equal the count on the Dial
  shown: int            // at most 10
  header: string | null // "Showing 10 of 36 matches" · "Showing all 4 matches" · "Showing 1 match" · null when total 0
  results: Card[]       // rank order
}
Card = { vehicle_id: uuid, year, make, model, variant,
         rating: number,        // 1 dp at this stop
         band: int, co2_g_km: int, driveaway_cents: int,
         coo_pa_cents: int,     // Pure Cost
         price_basis: string,   // for the ⓘ substantiation label
         image_url: string | null }
```

| Status | When |
|---|---|
| 200 | Normal. Empty band: `total 0, shown 0, header null, results []` (rare — button greys out). |
| 400 `invalid_params` | state not one of the eight codes; budget not a multiple of 5,000 in 20,000–200,000; stop or band outside 1–5. |
| 401 | Signed out. |
| 403 `upgrade_required` | Free plan (button is locked on Free). |
| 409 `dataset_stale` | `v` ≠ server's `scoring_version` — browser refetches dataset, recomputes, **leaves the needle where it is**, retries once. |
| 429 | Rate-limited (scoped "search" rate: 20/min). |

Each card shows: one-decimal rating at the user's stop, CO₂ in g/km, Est. Driveaway Price, and **Est. COO p.a. on Pure Cost**.

---

## 8 · The current car and the state

**Current car's Pure Cost COO p.a.** — from `GET /api/my-garage/current-vehicle/` (`engine_data.total_annual_cost`, integer cents). It must be costed like the band's cars:

| Current car saved as | Source of its Pure Cost COO |
|---|---|
| A catalogue car | Stored Mode B COO (col W) for that listing and state. |
| A Green Vehicle Guide record (most older cars) | Fixed costs: class medians rebuilt from the Mode B rows, by class and state. Fuel/electricity: the car's own GVG consumption through the standard cost formulas, at its class kilometres and the state's prices. ⓘ: "Estimated from your car's fuel use and class averages." |
| Manual entry only | **No figure.** Est. Cost Difference stays hidden. Never guess. |

**The state** — every dollar depends on it; never assumed, never defaulted to "NSW":

1. The user's saved state (`UserPriorityState.state` — one of ACT, NSW, NT, QLD, SA, TAS, VIC, WA; free-match answers fill it at sign-up), else
2. the current car's state (`CurrentVehicle.state`), else
3. ask once, **before any figure shows**, with an eight-state picker, and save the answer to (1).

Reject anything but the eight upper-case codes.

**Saving the sliders:** `PATCH /api/my-garage/priority-state/` with any of `priority_slider_position` (1–5, default **1**), `budget_max` (whole dollars, multiple of 5,000, 20,000–200,000; null = state default), `state`. Validate all three. Send **0.8 s after the user lets go** — one call per finished move. Response is `{ state: {…} }` only — no band counts (the browser computes them).

---

## 9 · Acceptance tests — must pass before handover

**Golden case: NSW, budget $60,000, stop 1 (Mostly cost), current car at $5,000/yr Pure Cost:**

| Band | Models | COO | CO₂ | Est. Cost Difference | List header |
|---|---|---|---|---|---|
| Captain Carbon™ | 36 | $6,203 | 2,958 kg | −$1,203 | Showing 10 of 36 matches |
| The Detour™ | 75 | $5,754 | 2,475 kg | −$754 | Showing 10 of 75 matches |
| Steady Cruiser™ | 34 | $5,259 | 1,965 kg | −$259 | Showing 10 of 34 matches |
| Smart Move™ | 42 | $4,494 | 0 kg | $506 | Showing 10 of 42 matches |
| Every Day Legend™ | 22 | $4,022 | 302 kg | $978 | Showing 10 of 22 matches |

The needle opens on **Every Day Legend™**. Its breakdown: electricity $635.73, CTP $572.00, comprehensive $1,816.34, registration $475.00, servicing $345.90, tyres $176.80; total $4,021.77.

**Second worked case: NSW, budget $200,000+, stop 1, user turns the needle to Steady Cruiser™** — window $185,000+, band holds 7 versions collapsing to **4 models** (Porsche 718 Boxster, Aston Martin Vantage Coupe, Jaguar F-TYPE R, Range Rover SE). COO = mean of middle two = $6,479.76 → shown **$6,480**; CO₂ = **3,185 kg**; with a $5,000 current car the difference shows **−$1,480** in warning colour; green button reads **"Showing all 4 matches"**.

**Also run by hand:** $150,000 at Mostly green — Captain Carbon™ is empty ("—" everywhere, button greyed); $200,000+ — the make cap leaves "Showing 8 of 12 matches" on Captain Carbon™.

**On-screen acceptance:**
1. Same car in any two states → identical rating and band.
2. Switch the CORE Mode selector → **the Dial does not change**; the car cards do.
3. Step through the five stops → pills and helper lines match section 3; the needle stays put; counts change.
4. Both golden cases match on screen to the dollar.
5. Network tab: **no request while dragging**; one PATCH per finished move; the dataset call carries no vehicle names.
6. Load a new `scoring_version` mid-session → the next green-button tap gets one 409, refetches, and shows a list whose total equals the dial's count.

---

## 10 · Known wrong behaviours — do NOT reproduce these

These are the bugs in the current implementation that this rebuild must eliminate:

1. **Dial following the CORE Mode selector** → Dial is Pure Cost always (rule 1).
2. **Per-state ratings** (same car 0.6★ in one state, 4.4★ in another) → one national rating per vehicle and mode (rule 2).
3. **Server re-scoring on slider moves / old weight params** (`weight_price`, `weight_emissions`, continuous 0–1 weights, old stops 100/0 … 0/100 with default stop 2 or 3) → five fixed stops, default stop 1, browser re-weights (section 3).
4. **Python `round()` / JS `toFixed()`** → half-up rounding everywhere (rule 4).
5. **Guessing money units from magnitude** (multiplying anything under 1,000,000 by 100 — which turned $638 servicing into $63,800) → integer cents at rest, annual per-state fields (rule 5).
6. **Counts/medians/needle computed from the user's garage cars** → computed from the market dataset in the budget window (section 6).
7. **Est. Cost Difference falling back to a "category average"** when there's no current car → hidden entirely (section 6.2).
8. **Subtracting resale credit in cost modes** (produced negative costs) → Mode C = Base + (driveaway − resale) ÷ 5; Mode F = C + finance; never negative. (Modes C/E/F matter for car cards only, never the Dial.)
9. **Needle opening on the band with the most cars** → highest band with at least one car (section 6.3).
10. **Price bins (±3 bins) instead of an honest window** → ±$15,000, both ends included; range line states the exact range (section 4).
11. **State silently defaulting to "NSW" or accepting any string** → the state chain, eight validated codes (section 8).
12. **Vehicle names in the Dial dataset** → names only via the matches endpoint, 10 at a time, paid plans (section 2).

---

## 11 · Reference figures for spot-checking (from the source workbook)

2025 Alfa Romeo Giulia Quadrifoglio, ACT, Large class, Mode B:
- Base (Pure) COO p.a. = **$6,714.04** → `coo_pa_cents` 671404; parts: fuel $2,987.46, electricity $0, CTP $404.18, comprehensive $1,890.00, registration $532.00, servicing $638.00, tyres $262.40, road-user charge $0.
- `price_score` = 0.405697, `emissions_score` = 0.426136 → core = 0.80×0.405697 + 0.20×0.426136 = 0.409785 → **2.0★**, band 2 (The Detour™). CO₂ cap at 205 g/km is 3.4 — doesn't bite.
- Annual CO₂ = 205 g/km × 14,000 km ÷ 1000 = **2,870 kg**.

Dataset size sanity check: 1,202 listings × 8 states × 4 modes = 38,464 source rows; ~1,173 on-sale rows per state in the Dial dataset; ~27 KB gzipped.

---

*Basis: "CORE Dial, Ratings and Data — Developer Guide", 7 Oct 2026 v2 (decisions D28–D32), and workbook 02 Vehicles & CORE (Consolidated Vehicles v6.4). Where any older spec disagrees, this prompt wins.*
