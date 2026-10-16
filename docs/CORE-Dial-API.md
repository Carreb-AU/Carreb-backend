# CORE Dial — API & Integration Guide (v6.4, Pure Cost)

> For frontend developers and testers. Everything below is verified against the
> deployed backend (`https://api.carreb.com.au`) on 16-Oct-2026.
> All money fields are **integer cents** (e.g. `6000000` = $60,000). Never floats.

---

## 1. What the CORE Dial is

A semicircular dial with five bands (1★ → 5★). The user sets:

- **My Budget** — a slider, $20,000–$200,000 in $5,000 steps.
- **My Priority** — five stops, from cost-focused (1) to green-focused (5).

For the band under the needle, the Dial shows: number of matching car
**models**, typical annual cost of ownership (**COO p.a.**), typical annual
**CO₂**, and the cost difference vs the user's current car. A green button
opens a list of up to 10 matching cars.

Band names (hardcoded, never from data):

| Band | Name |
|---|---|
| 1★ | Captain Carbon™ |
| 2★ | The Detour™ |
| 3★ | Steady Cruiser™ |
| 4★ | Smart Move™ |
| 5★ | Every Day Legend™ |

**Architecture rule (important):** the server never re-scores on a slider
move. The browser downloads the dataset **once per state**, then re-weights
locally using the constants in §5. The matches endpoint is the only
server-side scoring call, and it exists so the *paid* green button can't be
faked client-side.

---

## 2. How the computation works

### 2.1 The five priority stops (stored/sent as an integer 1–5, never weights)

| Stop | W(price) | W(emissions) | Meaning |
|---|---|---|---|
| 1 | 0.80 | 0.20 | Mostly cost |
| 2 | 0.65 | 0.35 | Cost-leaning |
| 3 | 0.50 | 0.50 | Balanced |
| 4 | 0.35 | 0.65 | Green-leaning |
| 5 | 0.20 | 0.80 | Mostly green |

Default stop: **1**. Helpers (for UI copy) per stop are in
`apps/vehicles/services/core_dial.py` (`PRIORITY_STOP_HELPERS`).

### 2.2 Budget window

Budgets are whole dollars, multiples of $5,000, in $20,000–$200,000.
The window is **±$15,000, both ends inclusive**:

- $60,000 → cars priced **$45,000–$75,000**
- $200,000 (or anything at the cap) → **$185,000 and up** (no upper bound)

### 2.3 Rating each car (per listing version, at a given stop)

```
core      = W(price) × price_score + W(emissions) × emissions_score   # 0..1
rating    = min( round_half_up(core × 5, 1dp), co2_cap )             # 0.0–5.0
band      = round_half_up(rating, 0dp)                               # 1–5
```

- `price_score` / `emissions_score` come from the dataset rows (0–1,
  precomputed nationally, 6 decimal places, round-half-up).
- **CO₂ cap** (from tailpipe CO₂, petrol/diesel only — BEV/FCEV never capped):

| CO₂ g/km | rating capped at |
|---|---|
| ≥ 250 | 2.4 |
| ≥ 200 | 3.4 |
| ≥ 150 | 4.4 |
| < 150 | no cap |

- **Round-half-up everywhere**, like Excel `ROUND`. JavaScript's
  `Math.round` is fine for positives; do **not** use banker's rounding.

### 2.4 From rated cars to the five band stats

1. Keep only listings whose `driveaway_cents` falls inside the budget window.
2. Rate each, assign to a band.
3. Rank within each band: **rating DESC, then COO p.a. ASC, then version_id ASC**.
4. **Deduplicate to one entry per `model_id`** in rank order. A model whose
   versions land in two bands counts in **both** bands.
5. Per band, report:
   - `count` — number of distinct models
   - median `coo_pa_cents` across those models
   - median `annual_co2_kg` across those models

### 2.5 Needle position on open

The needle opens on the **highest band with at least one model**; if all
bands are empty, band 3.

### 2.6 The green button (matches list)

- Selection: **pass 1** — one model per make (in rank order); **pass 2** — a
  second model per make. Max **10**, never padded with worse cars.
- Header strings: `Showing 1 match` / `Showing all N matches` (when N ≤ 10) /
  `Showing 10 of N matches`. `null` when the band is empty.

### 2.7 Current-car cost difference

The "cost difference vs your current car" figure uses the current vehicle's
Pure-Cost COO: GVG cars are costed from their own fuel/electricity consumption
plus class/state medians for fixed parts; manually entered cars get **no
figure**. State resolution order: `priority_state.state` → current vehicle's
state → no figure.

---

## 3. API reference

Auth for all endpoints: `Authorization: Bearer <access JWT>`.
Get a JWT with `POST /api/users/login/` → `{ "access": "...", "refresh": "..." }`.
Tokens expire (~1 day); use `POST /api/users/token/refresh/` to renew.

### 3.1 `GET /api/my-garage/priority-state/` — the Dial's saved state

Returns (and auto-creates on first call) the user's saved dial state.

```json
{
  "state": {
    "state": "NSW",                      // 3-letter code or null (→ use current car's state, else NSW)
    "budget_min": null,
    "budget_max": 60000,                 // null = state default; validated: 20000–200000, step 5000
    "priority_slider_position": 3,       // 1–5, default 1 (Mostly cost)
    "active_core_mode": "pure_cost",     // v6.4 dial is pure_cost only
    "updated_at": "2026-10-16T00:00:00Z"
  }
}
```

### 3.2 `PATCH /api/my-garage/priority-state/` — persist slider changes

Partial update. Send only what changed:

```json
{ "priority_slider_position": 4, "budget_max": 80000, "state": "VIC" }
```

Response: `{ "state": { ... } }` only — **no band data**. Band counts are
computed in the browser from the dataset (§5). Validation failures return
400 with `priority_slider_position: ["invalid_stop"]` or
`budget_max: ["invalid_budget"]`. Requesting a premium `active_core_mode` on
the Free tier returns 403. FreeMatch wizard sign-up pre-fills this state
(wizard state/stop/budget) automatically.

### 3.3 `GET /api/core-dial/dataset/?state=NSW` — the Dial dataset

**Fetch once per state, never on a slider move.** Available to all tiers —
the locked dial still shows COO and CO₂ to Free users.

Response `200`:

```json
{
  "scoring_version": "v6.4-rebatch-07Oct26 (assumptions 25-Sep-26; national ratings; C/F value lost)",
  "state": "NSW",
  "as_at": "2026-10-14",
  "rows": [
    {
      "version_id": 1,
      "model_id": "a57d2e70a1b6",        // SHA-256("year|make|model")[:12] — hash only, NO names in the dataset
      "driveaway_cents": 7000000,
      "coo_pa_cents": 576528,            // Pure Cost (Mode B) annual cost of ownership
      "annual_co2_kg": 3091.0,
      "price_score": 0.315777,
      "emissions_score": 0.375,
      "co2_cap": 4.4,                    // or null (no cap / BEV / FCEV)
      "parts_cents": { "fuel": 244114, "electricity": 0, "ctp": 57200,
                       "comprehensive": 163554, "registration": 68000,
                       "servicing": 27500, "tyres": 16160, "road_user_charge": 0 }
    }
  ]
}
```

~1,200 rows per state (~27 KB gzipped). **Caching is mandatory:**
`ETag: "v6.4-rebatch-07Oct26 (...):NSW"` (weak `W/"..."` form after gzip —
both accepted) and `Cache-Control: private`. Store the ETag; send
`If-None-Match` on subsequent loads → `304 Not Modified`, no body.

| Status | Meaning |
|---|---|
| 200 | dataset (or 304 with `If-None-Match` match) |
| 400 `{"error":"invalid_params"}` | bad/missing state |
| 401 | no/invalid token |
| 404 `{"error":"no_dataset"}` | no batch built yet (ops: run `build_core_dial`) |

### 3.4 `GET /api/core-dial-matches/` — the green button (paid)

**Paid plans only**; Free gets 403. Throttled to **20/minute per user** (429
when exceeded). This is the only call that triggers server-side scoring.

Query params — **all five required**:

| Param | Rules |
|---|---|
| `state` | one of ACT, NSW, NT, QLD, SA, TAS, VIC, WA |
| `v` | `scoring_version` string from the dataset response (URL-encode it) |
| `stop` | 1–5 |
| `budget` | whole dollars, multiple of 5000, 20000–200000 |
| `band` | 1–5 (the band under the needle when the user tapped) |

Response `200`:

```json
{
  "scoring_version": "v6.4-rebatch-07Oct26 (...)",
  "total": 22,                            // distinct models in the band
  "shown": 10,
  "header": "Showing 10 of 22 matches",   // or "Showing all 4 matches" / "Showing 1 match" / null
  "results": [
    {
      "vehicle_id": "b9052e77-bfca-462e-bb90-af158af1e905",   // catalogue vehicle UUID (deep link target)
      "year": 2025, "make": "Alfa Romeo", "model": "Giulia", "variant": "Veloce",
      "rating": 3.8, "band": 4,
      "co2_g_km": 246,
      "driveaway_cents": 7000000,
      "coo_pa_cents": 576528,
      "price_basis": "RAB (driveaway)",
      "image_url": "/media/vehicle_images/....jpg"           // may be null
    }
  ]
}
```

| Status | Meaning |
|---|---|
| 200 | matches list |
| 400 `{"error":"invalid_params"}` | any param missing/invalid |
| 401 | no/invalid token |
| 403 `{"error":"upgrade_required"}` | Free tier → show paywall |
| 404 `{"error":"no_dataset"}` | no batch built |
| 409 `{"error":"dataset_stale","scoring_version":"<current>"}` | client's `v` is old → **refetch the dataset**, don't retry as-is |
| 429 | throttle; back off |

### 3.5 Removed endpoints (do not call)

- `GET /api/core-dial/band-breakdown/` — **deleted**. Band stats come from the
  dataset + §5 computation, or from the matches response.

---

## 4. End-to-end flow — testing CORE Dial as a user

This is the exact sequence a user (or a tester with curl, or the frontend)
should follow.

### Step 0 — log in

```bash
curl -sS -X POST https://api.carreb.com.au/api/users/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "..."}'
# → { "access": "<JWT>", "refresh": "..." }
```

(2FA-enabled accounts get a challenge response instead — for testing, use a
non-2FA account.)

### Step 1 — load the saved dial state

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://api.carreb.com.au/api/my-garage/priority-state/
```

Gives you `priority_slider_position` (default 1), `budget_max` (may be null =
use default), and `state` (may be null).

### Step 2 — resolve the state to show

`state = priority_state.state || currentVehicle.state || "NSW"`. To check the
current vehicle: `GET /api/my-garage/current-vehicle/`.

### Step 3 — fetch the dataset (once per state, cache it)

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.carreb.com.au/api/core-dial/dataset/?state=NSW"
```

Save `scoring_version`, `as_at`, the ETag, and the rows.

### Step 4 — render the dial (browser computes, using §5)

Apply budget default if `budget_max` was null, compute the five bands with the
§5 algorithm, place the needle on the highest non-empty band, and show per
band: model count, median COO, median CO₂. Every slider move (budget or stop)
recomputes **locally** — no API call.

### Step 5 — persist slider changes (optional, debounce)

```bash
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"priority_slider_position": 4, "budget_max": 80000}' \
  https://api.carreb.com.au/api/my-garage/priority-state/
```

### Step 6 — the green button

```bash
curl -G -H "Authorization: Bearer $TOKEN" \
  "https://api.carreb.com.au/api/core-dial-matches/" \
  --data-urlencode "state=NSW" \
  --data-urlencode "v=<scoring_version from step 3>" \
  --data-urlencode "stop=4" \
  --data-urlencode "budget=80000" \
  --data-urlencode "band=<band under the needle>"
```

Handle: 403 → paywall screen; 409 → refetch dataset (Step 3) then retry;
429 → back off; else render `header` + `results` (max 10).

**Happy-path smoke test (free account):** Steps 0–5 all work; Step 6 must
return 403 `upgrade_required`. **Happy-path smoke test (paid account):**
Step 6 returns 200 with up to 10 named cars.

---

## 5. Client-side constants (must match the server exactly)

```js
const STOPS = { 1:[0.80,0.20], 2:[0.65,0.35], 3:[0.50,0.50], 4:[0.35,0.65], 5:[0.20,0.80] };
const BUDGET = { MIN: 20000, MAX: 200000, STEP: 5000, WINDOW: 15000, TOP: 185000 };
const BAND_NAMES = { 1:'Captain Carbon™', 2:'The Detour™', 3:'Steady Cruiser™',
                     4:'Smart Move™', 5:'Every Day Legend™' };

// round-half-up, n decimal places (positive numbers)
const rhu = (x, dp=0) => { const f = 10**dp; return Math.floor(x*f + 0.5 + 1e-9)/f; };

function windowCents(budget) {
  if (budget >= BUDGET.MAX) return [BUDGET.TOP*100, null];       // $185k and up
  return [Math.max(0, budget-BUDGET.WINDOW)*100, (budget+BUDGET.WINDOW)*100]; // inclusive both ends
}

function rate(row, stop) {
  const [wp, we] = STOPS[stop];
  const core = wp*row.price_score + we*row.emissions_score;
  const rating = Math.min(rhu(core*5, 1), row.co2_cap ?? Infinity);
  return { rating, band: Math.max(1, rhu(rating, 0)) };
}

function computeBands(rows, budget, stop) {
  const [lo, hi] = windowCents(budget);
  const inWindow = rows.filter(r => r.driveaway_cents >= lo && (hi === null || r.driveaway_cents <= hi));
  const bands = {};
  for (let b = 1; b <= 5; b++) {
    const ranked = inWindow
      .map(r => ({ row: r, ...rate(r, stop) }))
      .filter(t => t.band === b)
      .sort((a, c) => c.rating - a.rating || a.row.coo_pa_cents - c.row.coo_pa_cents || a.row.version_id - c.row.version_id);
    const seen = new Set(), models = [];                       // one per model_id, in rank order
    for (const t of ranked) if (!seen.has(t.row.model_id)) { seen.add(t.row.model_id); models.push(t); }
    // median: middle value, or mean of the two middle ones when even
    const med = xs => { if (!xs.length) return null; const s = [...xs].sort((a, b) => a - b);
                        const m = s.length >> 1;
                        return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
    bands[b] = {
      count: models.length,
      coo_pa_cents: med(models.map(m => m.row.coo_pa_cents)),
      annual_co2_kg:  med(models.map(m => m.row.annual_co2_kg)),
    };
  }
  return bands;
}

const needleBand = bands => { for (let b = 5; b >= 1; b--) if (bands[b].count > 0) return b; return 3; };
```

(For production, copy `compute_bands`/`median_or_none` semantics from
`apps/vehicles/services/core_dial.py` — including even-count medians as the
mean of the two middle values.)

---

## 6. Quick reference — error handling matrix

| Endpoint | 400 | 401 | 403 | 404 | 409 | 429 | 304 |
|---|---|---|---|---|---|---|---|
| `priority-state` GET/PATCH | invalid fields | unauthenticated | premium mode on free | — | — | — | — |
| `core-dial/dataset/` | invalid `state` | unauthenticated | — | `no_dataset` | — | — | with `If-None-Match` |
| `core-dial-matches/` | `invalid_params` | unauthenticated | `upgrade_required` | `no_dataset` | `dataset_stale` | throttled | — |

---

*Backend source of truth: `apps/vehicles/services/core_dial.py` (algorithm),
`apps/vehicles/views_core_dial.py` (endpoints), `apps/mygarage/views.py`
`PriorityStateView` (saved state). Data is loaded by
`python manage.py build_core_dial --path <workbook.xlsx> --clear`.*
