# Frontend API Guide — Register Amendments, 6-Nov-26 (Pre-Launch Blockers)

**For:** Meenam / Abdullah (frontend) · **From:** Ali (backend)
**Companion to:** "Frontend API Guide — FINAL Launch Integration (9-Nov-26)" — that guide still stands; this document adds the changes from Jock's 6-Nov reconciliation email and supersedes specific lines where noted.
**Backend dataset:** `v6.4-audit-04Nov26`, live on `api.carreb.com.au`. Backend code on GitHub: https://github.com/alirehan/Carreb-backend (`main`, through `5e672f1`).

Golden rule unchanged: **render what the payload says, never hard-code** — band names, slugs, directions, km copy all come from the API.

---

## 1. 5★ band name — CORRECT values (BLOCKER, supersedes Flag 7 in §13 of the main guide)

Jock has confirmed the trademark filing: the band is **"Everyday Legend™" (one word)**, slug **`everyday-legend`**. "Every Day Legend" was the stale label. The dataset rows carrying "Everyday Legend™" are the correct ones.

- Backend fix lands before FE integration: the three hardcoded maps that produced the wrong label/slug (`rating_engine.py:25,45`, `core_dial.py:22`, `uncosted_estimates.py:93`) are being corrected to the payload values above.
- **FE action:** render `band_name` / `band_slug` from the payload everywhere (5★ band tooltip, Dial band list, badge, RideReveal). Never hard-code either spelling. Verify against:
  ```bash
  curl -s "https://api.carreb.com.au/api/vehicles/2f6beb87-aa31-4496-bb17-39cc58839ce9/?state=NSW" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['engine_data']['band_name'], '|', d['engine_data']['band_slug'])"
  # expect: Everyday Legend™ | everyday-legend   (after the BE fix deploys)
  ```
- Update the tooltip paste (main guide §13, Flag 7): the 5★ band tooltip heading is "Everyday Legend™".

## 2. Est. Cost Difference — neutral zero (BLOCKER, B-34)

`direction` now has a third value and FE must handle it:

| `direction` | Render | Colour |
|---|---|---|
| `more_expensive` | **"+$X/yr more"** | amber |
| `saving` | **"−$X/yr less"** | green |
| `same` | **"$0/yr"** | neutral (no amber/green) |

Backend change: `same` fired only on an exact zero; it now also fires when the difference rounds to $0/yr (near-identical cars). `value_cents` stays unsigned; derive sign from `direction` only. Tooltip (CD-04/CC-03) unchanged.

## 3. CORE Dial — 109 more vehicles in bands, counts and "View … vehicles" (BLOCKER)

Jock's arithmetic (12,248 dial rows ÷ 8 = 1,531 vs 1,640 live) is right, but the excluded 109 are **not "Other" category** — the 04-Nov file has zero live "Other" vehicles. They are live cars gated out by a backend Research Status filter: **104 "Pending verify" + 5 "Coming FY26"**. Per the locked rule ("is_suppressed is the only gate") they belong in the Dial.

- Backend fix: the status gate is removed from the dial build; the batch is rebuilt (1,531 → **1,640** listings, 12,248 → **13,120 rows**).
- **FE impact:** none structural — but **band counts, the Dial percentages, and every "View … vehicles" / band list will change slightly** after the rebuild. Re-screenshot any Dial states you've captured. No FE code change; just don't be surprised by shifted numbers, and never cache dial counts client-side.

## 4. Pure Cost rule (new section — Jock asked for this explicitly)

What "Pure Cost" means on every surface, so figures never mix bases:

- **Pure Cost (Mode B)** = the running-cost lines only: fuel/energy, CTP, comprehensive insurance, registration, servicing, tyres, EV road-user levy. **No finance, no depreciation/resale** — those exist only in True Value (C) and Full Picture (F). `annual_cost_breakdown.finance_annual` and `resale_credit_annual` are 0 in Pure Cost by definition.
- **Mode switching is client-side** (main guide §12): read `mode_data_by_state.<state>.<B|E|C|F>` / `mode_annual_costs` for the mode on screen; no refetch on mode switch. Mode letters: `B` = Pure Cost, `E` = COOL Choice, `C` = True Value, `F` = Full Picture.
- **Every dollar surface follows the selected mode**: card total, Est. Cost Difference (both sides at the same mode), Dial baseline, hero. A Pure Cost card compared against a Full Picture baseline is a bug — the payload always pairs them; render as sent.
- **Ratings/stars never follow km or mode switches**: stars, the Dial, and bands stay on dataset km (D29/D30). Only dollars move with the user's km setting.
- Sanity anchor (009, NSW): `mode_annual_costs.pure_cost` ≈ $7.7k vs `full_picture` ≈ $29.4k — the gap is finance + depreciation. If your rendered Pure Cost figure is ever in the tens of thousands for a $150k car, you're showing the wrong mode.

## 5. Smart Car Finder — star filter and header contract (B-14/B-33, Jock decisions)

Backend adds to `GET /api/vehicles/` before Sunday: budget ceiling (hard cap), the G-146 filters, the **star filter**, and the downward-only relaxation ladder. Jock's ruling on the star filter: **exact band** — 3★ means rating 2.5–3.4 inclusive (bands: 1.0–1.4, 1.5–2.4, 2.5–3.4, 3.5–4.4, 4.5–5.0).

FE contract (unchanged from main guide §9, restated):
- Strict: header "Showing N of M matches".
- Relaxed: same header **plus one line naming the widening** ("Fewer than 5 under your budget, so we widened down to $X"). Downward only, never above budget.
- Never "0 matches"; never "based on what you told us" when nothing relaxed; one-decimal ratings on result cards.

## 6. km badge — label change (B-02, Jock decision + B-38)

Jock: a km figure derived from the odometer is not a user edit — label it "from your odometer", not "Your input". **Superseded before launch by B-38**: the odometer derivation is retired entirely (km p.a. is a direct user input only), so there is no derived case left. Final labels:
- Untouched (12,100 ABS pre-fill): badge **"Default"**.
- User typed a km: badge **"Your input"** (amber) — main guide §1.
- Odometer + purchase date fields remain, optional, labelled as feeding the **resale estimate only**; saving them changes no cost figure.

**Post-launch (patch 1, Abdullah):** km control moves to the MyGarage header beside Mode — label **"Your km a year"**, line beneath: **"Changes cost estimates. Ratings use standard km."** Same `garage_km`, same `PATCH /api/my-garage/priority-state/`; only placement changes.

## 7. Settings — real next charge date (billing)

`GET /api/users/profile/` now returns two new fields:
```json
"next_charge_date": "2027-10-15T00:00:00Z",   // null for free users
"cancel_at_period_end": false
```
- Render "Next charge: 15 Oct 2027" formatted `en-AU` (day month year).
- `next_charge_date: null` → **hide the status bar entirely** (the old hardcoded "Jan 1, 2027" placeholder is removed).
- `cancel_at_period_end: true` → show "Subscription is scheduled to be canceled at the end of the billing period." (also the case after a downgrade until period end).

## 8. RideReveal — plate graphic and share (B-16/B-36)

- **Plate graphic:** backend fix coming — the PNG plate header was hardcoded "WESTERN AUSTRALIA"; it will render the user's state or no state name. **FE: nothing to do**; verify a QLD user's card after deploy.
- **Guard:** backend ships the guard log from three regenerated cards (third person, US spelling, advice words, performance claims) as proof; FE only renders the disclaimer line under the modal card and the footer strip on the 1080 PNG.
- **Share (B-36):** backend is building the stable PNG URL + public result page with og tags (`og:image` = the 1080 PNG, `og:title` = headline). Until it lands, share flows use the existing `share_image_url` from the result payload. Final flow: mobile = Web Share API with the PNG file; desktop = per-channel intents with the **result URL**; Instagram = download fallback; copy-link = result URL.

## 9. What did NOT change (save yourself the work)

- **Held cars:** still selectable as current vehicle only; still never in matches, bands, counts or the Dial; still amber notice + "Default" badges (main guide §3).
- **Match cards:** only live rows of the current load (backend-enforced; removed/suppressed listings can never appear). Existing garages referencing a now-suppressed row keep their card — that's intentional (B-22/B-23), not a match card.
- **`core_arcs` needle stub:** a needle of exactly 0 still renders as a ~3% stub on both arcs (B-37); genuinely `null` needles (no bounds row) render no arc. With this load there are no live "Other" vehicles, so null-needle arcs should not appear in practice — log it if you see one.
- **Mode letters and payload shapes:** unchanged and additive only.

---

## Verification curls (no auth)

```bash
# Band name after BE fix
curl -s "https://api.carreb.com.au/api/vehicles/2f6beb87-aa31-4496-bb17-39cc58839ce9/?state=NSW" \
  | python3 -c "import json,sys; d=json.load(sys.stdin)['engine_data']; print(d['band_name'], d['band_slug'])"

# Dial row count after rebuild (expect 13120)
curl -s "https://api.carreb.com.au/api/vehicles/core-dial/bands/?state=NSW" -o /dev/null -w '%{http_code}\n'
# (band totals in the response should sum to 1640 vehicles)

# Neutral direction appears once BE ships the round-to-$0 fix
curl -s "https://api.carreb.com.au/api/my-garage/vehicles/" -H "Authorization: Bearer <token>" \
  | python3 -c "import json,sys; [print(v['vehicle_data']['name'], v['engine_data']['est_cost_difference']['direction']) for v in json.load(sys.stdin)['vehicles']]"
```

---

*Backend contact: Ali. Anything here that doesn't match what the API returns is a backend bug — send the curl + response and I'll fix it.*
