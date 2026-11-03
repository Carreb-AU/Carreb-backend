# Frontend API Guide — Garage km Normalisation & Energy-Cycle CO₂ (B-21, Nov 2026)

For: Abdullah (frontend) · Backend: B-21 garage-level km normalisation

## What changed and why

Every card in MyGarage (current vehicle **and** garage vehicles) is now costed
at one km/yr figure — the user's **garage km** — instead of each car's own
category km. This makes the "Est. Cost Difference" between cards a fair
side-by-side.

The garage km resolves in this order (backend does this; you just display):

1. **User's own setting** — set once in Edit Vehicle (this now works; see API
   below). Locked against odometer re-derivation.
2. **Odometer-derived** — current vehicle's `odometer_reading ÷ years since
   purchase_date`, rounded to 100 (B-02 guard rails: 3,000–60,000 km/yr).
3. **Default 12,100 km/yr** (ABS SMVU 2020, all vehicles) when there is no
   usable odometer.

Only km-dependent cost lines scale (fuel/electricity, servicing, tyres, EV
road-user levy, annual CO₂ kg). Rego, CTP, insurance, finance and resale
never scale. **CORE rating and stars never change with km** (dataset values,
D29/D30) — km moves dollars only.

## New keys in `engine_data` (current vehicle and every garage card)

```json
"costed_km": 12100,
"costed_km_source": "default",          // "user" | "odometer" | "default"
"costed_km_copy": "Costed at 12,100 km/yr (ABS 2020). Change in Edit Vehicle.",
"personalised_estimate": false
```

- `costed_km_copy` is the exact one-line string to render under the card
  dollars. When source is `default`:
  `"Costed at 12,100 km/yr (ABS 2020). Change in Edit Vehicle."`
  When source is `user` or `odometer`:
  `"Costed at 14,000 km/yr, your setting."`
- When `personalised_estimate` is `true`, also show the D22 badge:
  **"Personalised estimate based on your inputs and Carreb's assumptions.
  Not a guarantee."**
- Same keys are in `meta.costed_km` / `meta.costed_km_source` (top level of
  the response) in case `engine_data` is absent.

All dollar figures on the card (`total_annual_cost`, `annual_cost_breakdown`
lines, `mode_annual_costs`, `est_cost_difference`) are already at
`costed_km` — no frontend math needed. The difference vs the current vehicle
is computed backend-side at the same km, mode and state.

## New key: energy-cycle CO₂ g/km (fixes the "~0 g/km" on EVs)

`engine_data` now includes:

```json
"co2_energy_cycle_g_per_km": 131.0,
"tailpipe_co2_g_per_km": 0.0,
"annual_co2_kg": 1961
```

For the **Est. CO₂ g/km card row, use `co2_energy_cycle_g_per_km`** (not
`tailpipe_co2_g_per_km`). For petrol/diesel cars it equals the tailpipe
figure; for BEVs it's grid scope 2+3 so the g/km row agrees with the kg p.a.
row instead of showing "~0". Keep `tailpipe_co2_g_per_km` only if some flow
specifically needs the tailpipe basis.

## Setting the user's km (Edit Vehicle)

Two equivalent ways; use whichever the modal already calls.

**Option A — with the current-vehicle save** (`POST /api/my-garage/current-vehicle/`):

```bash
curl -X POST https://api.carreb.com.au/api/my-garage/current-vehicle/ \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{
    "vehicle_catalogue_id": "<uuid>",
    "odometer_reading": 45000,
    "purchase_date": "2023-06-01",
    "state": "QLD",
    "garage_km": 15000
  }'
```

- `garage_km` is optional; 3,000–60,000 (whole km). Sending it marks the km
  as the user's setting (source becomes `"user"` on every card).
- Send `"garage_km": null` to unlock and go back to automatic (odometer or
  default).
- The response is the full calculated card — read `engine_data.costed_km`
  straight from it.

**Option B — priority state** (`PATCH /api/my-garage/priority-state/`):

```bash
curl -X PATCH https://api.carreb.com.au/api/my-garage/priority-state/ \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"garage_km": 15000}'
```

Response state now also echoes:

```json
{"state": {"garage_km": 15000, "garage_km_user_set": true, ...}}
```

After either call, **re-fetch the garage list** (`GET /api/my-garage/vehicles/`)
and the current vehicle — every card comes back already re-costed at the new
km. One edit updates every card, current and new.

## What did NOT change

- CORE rating, stars, band, the Dial dataset, Smart Match and Smart Car
  Finder: still dataset km. Don't re-derive anything.
- The environment slider still only re-ranks ratings; it never changes
  dollars or CO₂ (that is intended, D29/D30).
- `annual_km` in the garage card response is the km the card is costed at
  (GVG/AI cards); catalogue cards use `costed_km` above.
