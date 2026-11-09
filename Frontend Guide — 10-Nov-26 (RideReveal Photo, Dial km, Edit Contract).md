# Frontend Guide — 10-Nov-26: RideReveal Photo, Dial km Rescale, Edit Contract

**For:** Abdullah · **From:** Ali (backend) · **Live:** `api.carreb.com.au`, `main` at `4440959`.
**Companion:** "Frontend API Guide — COMPLETE Final (7-Nov-26)" — everything there stands; this is the integration addendum for the newest changes. Real request/response pairs below were captured from production.

---

## 1. RideReveal modal photo (the "image disappears on reopen" bug)

The modal photo must be uploaded to the backend — until now it only lived in component state, which is why it vanished on reopen (and why it "worked" for users with a profile picture: the card fell back to that). Three steps:

**Step 1 — upload the photo** when the user picks it (don't wait for generate):

```bash
curl -s -X POST "https://api.carreb.com.au/api/my-garage/ridereveal/photo/" \
  -H "Authorization: Bearer <token>" \
  -F "photo=@/path/to/image.jpg;type=image/jpeg"
```
Response (real, captured):
```json
{"photo_url": "https://api.carreb.com.au/media/ride_reveal_photos/image.jpg"}
```
JPEG/PNG/WebP only, 8 MB max — otherwise `400 {"error": "…"}`. No auth → 401.

**Step 2 — pass it in generate:**
```bash
curl -s -X POST "https://api.carreb.com.au/api/my-garage/ridereveal/generate/" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"garage_vehicle_id": "<uuid>", "photo_url": "https://api.carreb.com.au/media/ride_reveal_photos/image.jpg"}'
```
Same-origin media URLs only — a remote URL returns:
```json
{"error": "invalid_photo_url", "message": "photo_url must be a file uploaded to this site's media storage."}   // 422
```

**Step 3 — render it on reopen.** The result payload now carries `photo_url`:
```json
{"archetype_name": "…", "share_image_url": "…", "public_url": "…",
 "photo_url": "https://api.carreb.com.au/media/ride_reveal_photos/image.jpg"}
```
Render `result.photo_url` when present — it **wins over the profile picture**; when `null`, fall back to the user's profile photo, then the initial avatar. A photo-only change on an existing result re-renders the card free (no credit, no regeneration) — same as plate/colour/name edits.

---

## 2. CORE Dial — rescale rows to the user's km (blocker)

Dial dataset rows are costed at **each car's category km**; rows now tell you which:

```bash
curl -s "https://api.carreb.com.au/api/core-dial/dataset/?state=NSW" -H "Authorization: Bearer <token>"
```
Each row gained one field (rest of the shape unchanged):
```json
{"version_id": 1214, "model_id": "…", "driveaway_cents": 11650000,
 "coo_pa_cents": 589028, "annual_co2_kg": 1670, "km_pa_used": 14000,
 "price_score": 0.21, "emissions_score": 1.0, "co2_cap": null,
 "parts_cents": {"fuel": 0, "electricity": 84628, "ctp": 57200, "comprehensive": 179784,
                  "registration": 68000, "servicing": 57260, "tyres": 52480, "road_user_charge": 0}}
```

Before the band medians (`iw()`), rescale every row to the user's `costed_km` (from the current vehicle; no current vehicle or `km_pa_used: null` → no rescale):
```js
const k = userKm / row.km_pa_used;
const perKm = row.parts_cents.fuel + row.parts_cents.electricity
            + row.parts_cents.tyres + row.parts_cents.road_user_charge;
row.coo_pa_cents = row.coo_pa_cents + Math.round(perKm * (k - 1));
row.annual_co2_kg = Math.round(row.annual_co2_kg * k);
```
Insurance/CTP/rego/servicing stay fixed; use the rescaled COO for the sort tie-break; **never** touch `price_score`, `emissions_score` or bands.

**Anchor test (must match exactly):** Polestar 5 Dual motor, NSW, 12,100 km — `589,028` → `570,420` cents; CO₂ `1,670` → `1,443` kg.

---

## 3. Edit Vehicle contract — three rules that were biting

1. **Only PATCH fields the user actually changed.** Diff against the loaded values. Sending every cost field is what poisoned Jock's Polestar 5 with another car's figures (insurance 1207.64, rego 406, a 6 L/100km on a BEV…). Backend now also wipes overrides when the car is swapped, but don't rely on it.
2. **Override units are DOLLARS** (`insurance_override: 2500` = $2,500/yr; `resale_value_override: 20250` = $20,250). Display them as-is — the "**$203**" bug was a cents ÷100 format applied to a dollars value.
3. Editing **existing AI/GVG** garage vehicles works end-to-end now (list → save → figure moves). The add gate is unchanged: `POST /api/my-garage/vehicles/` still returns **400** for AI/GVG ids:
```json
{"detail": "Only Carreb catalogue vehicles can be added to My Garage."}
```
Handle it (show the message); don't treat it as an edit failure — edits go through `PATCH /api/my-garage/vehicles/<id>/details/`.

---

## 4. Dataset version note

The site now runs `v6.4-update-07Nov26` (1,645 live vehicles, dial 13,160 rows, EV estimator sample 311). The homepage "1,498+" figure is hardcoded FE copy — update it. Band counts and "View … vehicles" lists shifted with the new data; never cache dial counts client-side.

---

*Backend contact: Ali. Anything here that doesn't match what the API returns is a backend bug — send the curl + response.*
