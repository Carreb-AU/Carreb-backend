# Backend Reply — 10-Nov-26: RideReveal Photo Persistence, AI/GVG Editing, Dial km Basis, 07-Nov Dataset

**To:** Jock · **From:** Ali (backend)
**Environment:** `api.carreb.com.au`, `main` at `4440959` (07-Nov dataset live as `v6.4-update-07Nov26`).
**Test suites:** mygarage 89 green, vehicles 90+ green.

Covers everything since the 7-Nov reply: the four items from your 9-Nov data check, the Edit Vehicle / AI-GVG register item, the RideReveal image issue, the 07-Nov dataset load, and the dataset-upload handover. Earlier rounds (estimator, caps, blockers B-37/38…) are in the previous reply docs.

---

## 1. Your 9-Nov data check — the four items

### 1.1 Dial km basis [was BLOCKER] — backend half done, anchor verified
Dial dataset rows (`/api/core-dial/dataset/`) now carry **`km_pa_used`** — the category km each row is costed at. The FE rescale to the user's `costed_km` is specced verbatim in the FE guide (your formula: `k = userKm/row.km_pa_used`; `coo += round(perKm×(k−1))` on fuel+electricity+tyres+RUC only; CO₂ × k; rescaled COO drives the sort tie-break; no rescale without a current vehicle; scores/bands untouched).

**Verified on production with your test case** — Polestar 5 Dual motor, NSW (category 14,000 km):
```
row coo_pa_cents 589,028 → rescaled @12,100 km = 570,420 ($5,704.20)
annual_co2_kg    1,670   → rescaled              = 1,443 kg ✓ (matches the vehicle card)
```
(One cent under your hand figure — plain `round()` of the half cent, per your own formula.)

### 1.2 Override carry-over [was BLOCKER] — fixed
Root cause: the Current Vehicle record is *reused* across swaps, so overrides attached to it leaked onto the next car. **Swapping the current vehicle now wipes its overrides** (re-saving the *same* car keeps them — test-locked). The FE half — Edit Vehicle must PATCH only fields the user actually changed — is in the FE guide; your Polestar 5 test vehicle's overrides were left in place per your instruction until Abdullah reproduces (say the word and I'll clear them).

### 1.3 Resale $203 [was BLOCKER] — backend contract confirmed; FE display fix
All overrides are **dollars at the API boundary** (`resale_value_override: 20250` = $20,250; the engine converts ×100 to cents internally — math verified). The "$203" is the FE applying a cents ÷100 format to a dollars value. Without the override your $62,107 is what the card computes. Display rule documented for FE.

### 1.4 Dial on 04-Nov [was BLOCKER] — LOADED ✓
The 07-Nov FINAL LAUNCH is live end-to-end:

| | 04-Nov (old) | 07-Nov (live) |
|---|---|---|
| scoring_version | v6.4-audit-04Nov26 | **v6.4-update-07Nov26** |
| live vehicles | 1,640 | **1,645** |
| dial rows | 13,120 | **13,160** |
| estimator NSW samples | petrol 499 / EV 308 | petrol 499 / EV **311** |

The load ran through the new upload pipeline (below) with a full audit row attributed to your account: 5 created / 1,775 updated, bounds synced, dial rebuilt — one dispatch.

**Found and fixed en route:** the arc/bounds lookups read a *hardcoded* version list that couldn't know the new version — the arcs would have silently kept using 04-Nov bounds. Lookups now follow the **current dial batch's version** first (bounds and dial always load from the same signed-off workbook), so no future monthly file can hit this. Homepage "1,498+" is FE copy for Abdullah.

---

## 2. Edit Vehicle for AI/GVG vehicles — restored, separation enforced

Investigated on production before changing anything. The edit list was **never** filtered — AI/GVG garage rows return with full cards (verified by seeding a test AI vehicle), and the FE save path never touches the add-to-garage gate. What was actually lost: the GVG/AI costing path silently ignored Edit Vehicle overrides — saves returned 200 and stored the value, but card figures never moved, so editing looked dead.

**Fix:** the GVG/AI costing path now applies overrides — insurance/registration/servicing/tyres (dollars) replace the matching class-median part *after* the km rescale (an overridden line is the user's figure, never factor-scaled); `resale_value_override` replaces the resale estimate. Verified live: an insurance edit on an AI garage card moves the figure.

**Separation:** add-to-garage still rejects new AI/GVG ids with 400 (test-asserted); editing existing rows never passes through that gate. No records deleted, migrated or re-idded; pricing/scoring/current-vehicle selection untouched.

---

## 3. RideReveal image persistence — fixed

Your observation was exact: the modal's uploaded image never left the browser (the generate payload carried nothing), the result had nowhere to store it, and the card sourced its photo from the **profile picture** — hence "works with a profile picture, lost without one".

**Backend (live):**
- `POST /api/my-garage/ridereveal/photo/` — multipart `photo` (JPEG/PNG/WebP, 8 MB) → `201 {"photo_url": …}` (verified: 201 authed, 401 anonymous).
- Generate accepts `photo_url` (same-origin media only; remote URLs → 422), stored on the result (`uploaded_photo`); the **result payload now returns `photo_url`**, so reopening the modal renders the persisted image. It wins over the profile photo; profile photo remains the fallback.
- A photo-only change on an existing result updates + re-renders the card **free** — no credit, no regeneration (same rule as plate/colour/name edits).

**FE half for Abdullah** (three calls, spec in the FE guide): upload → pass `photo_url` in generate → render `photo_url` from the result on reopen.

---

## 4. Dataset upload handover (the monthly self-service)

The admin page is live: `https://api.carreb.com.au/admin/` → **Dataset uploads → Upload monthly dataset** (your account `jock@carreb.com.au`, credentials sent separately). One upload refreshes vehicles + scoring bounds + CORE Dial with a permanent audit history (file, user, counts, bounds version, dial rows). The 07-Nov load above was its first production run. Loader is ready for the 1-Dec monthly naming (frozen tab names, Read-me version, extra tabs can never break it).

---

## 5. Still open (unchanged)
- **B-37** — Vercel env vars (`REACT_APP_ROBOTS_CONTENT=index, follow`, `REACT_APP_ALLOW_INDEXING=true`, Production scope, redeploy). The "Google sees us" check.
- **B-41** — production Stripe is in **test mode** with no price IDs configured; real payments cannot be processed until the live key + price IDs + webhook secret are swapped in. Needed from the Stripe dashboard.
- FE items for Abdullah are consolidated in the FE guide (COMPLETE Final + the 10-Nov addendum).

*Commits: `436dfb8` (dial km + swap-clears-overrides), `5845e6d` (AI/GVG edit restore), `c9ac8db` (bounds follow dial version), `4440959` (RideReveal photo + migration 0018). Anything here that doesn't match the API is a backend bug — send the curl + response.*
