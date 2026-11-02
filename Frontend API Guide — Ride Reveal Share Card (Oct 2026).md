# Frontend API Guide — Ride Reveal Share Card (Oct 2026)

> **Update (2 Nov 2026, deployed):** two backend fixes — see [section 4](#4-update-2-nov-2026-backend-fixes).

## What changed

The Ride Reveal result response has **one new field**:

| Field | Type | Meaning |
|---|---|---|
| `share_image_url` | string \| null | Absolute URL of a ready-to-share 1080×1350 PNG of the reveal card. `null` if not ready or rendering failed. |

Everything else in the response is unchanged. The PNG is generated **automatically in the background** right after a reveal is generated (takes a few seconds). No new endpoint to call, no params to send.

---

## 1. Get the reveal result (unchanged endpoint)

```bash
curl -sS "https://api.carreb.com.au/api/my-garage/ridereveal/result/<garage_vehicle_id>/" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

### Response (200) — new field highlighted

```json
{
  "archetype_name": "Smart Navigator",
  "archetype_tagline": "Make Every Penny Count",
  "self_insight_text": "Choosing the Omoda Jaecoo J8 reflects a desire for practicality…",
  "social_perception_text": "Others may perceive you as someone who prioritises practicality…",
  "did_you_know_fact": "The Omoda Jaecoo J8 offers innovative tech features…",
  "share_caption": "🚗✨ Proud owner of the Omoda Jaecoo J8 2027 …",
  "disclaimer": "for entertainment and educational purposes only",
  "custom_plate": "AXT1234",
  "favorite_color": "Midnight Blue",
  "generated_at": "2026-10-30T13:47:33.426851Z",
  "vehicle": {
    "make": "Omoda Jaecoo",
    "model": "J8",
    "year": 2027,
    "variant": "Premium AWD",
    "powertrain_type": "petrol",
    "image_url": "/media/vehicle_images/omoda-jaecoo-jaecoo-j8-2027.png",
    "core_rating": 3.2,
    "band_name": "The Smart Pick™"
  },
  "share_image_url": "https://api.carreb.com.au/media/ride_reveal_shares/5ef6166d-90b3-4ce2-b451-bfcffc4e7f8c.png"
}
```

When the image isn't ready (or rendering failed), the last line is:

```json
  "share_image_url": null
```

---

## 2. Sharing flow

```js
const result = await fetchRevealResult(garageVehicleId); // existing call

if (result.share_image_url) {
  // Preferred: share image + caption + link
  const imageFile = await fetch(result.share_image_url).then(r => r.blob());
  const file = new File([imageFile], 'ride-reveal.png', { type: 'image/png' });

  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    await navigator.share({
      files: [file],
      title: 'My Ride Reveal',
      text: result.share_caption,          // keep — platforms that accept files also show text
      url: `${FRONTEND_URL}/ride-reveal/${garageVehicleId}`,  // your public reveal/profile link
    });
  } else {
    // Desktop / unsupported: download the PNG, copy caption + link to clipboard
    downloadFile(result.share_image_url);
    copyToClipboard(`${result.share_caption}\n${FRONTEND_URL}/ride-reveal/${garageVehicleId}`);
  }
} else {
  // Fallback — same behaviour as today
  shareText(`${result.share_caption}\n${FRONTEND_URL}/ride-reveal/${garageVehicleId}`);
}
```

### Timing behaviour

| When you fetch | What you get |
|---|---|
| Immediately after the reveal completes | Usually `share_image_url` already present (render takes ~2–5 s, reveal AI takes ~5–20 s, so it often lands first). |
| Occasionally | `null` — the render is still running. |
| If rendering failed | `null` permanently for that reveal. Frontend must fall back to text sharing (no error state needed). |

**Recommended:** when the user opens the share sheet and `share_image_url` is `null`, re-fetch the result endpoint once after ~4 seconds. If still `null`, fall back to text. Don't poll more than once or twice.

---

## 3. Notes

- **PNG is 1080×1350** (Instagram portrait 4:5) — postable as-is.
- `share_image_url` is an absolute URL — no prefixing needed.
- The card already contains: name + archetype + tagline, vehicle photo, plate, favorite-color swatch (when the user picked a colour), self/social insights, did-you-know. `share_caption` and the link go in the share text, not the image.
- **Reveals generated before 30-Oct-2026 have no card** (`share_image_url: null` forever). They follow the text fallback — no special handling needed, same code path.
- `favorite_color` is still a plain string (e.g. `"Midnight Blue"`) — the swatch colour is applied server-side; nothing extra for you to map.
- No auth needed to *view* the PNG URL (same as vehicle images under `/media/`), but keep fetching it server-to-server or client-side with the token as you prefer — it's a plain static file.

---

## 4. Update (2 Nov 2026): backend fixes

### 4a. `first_name` is now accepted and returned

The generate endpoint now accepts an optional `first_name` (you already send it in `buildGenerateRideRevealBody` — it was previously dropped):

```bash
curl -sS -X POST "https://api.carreb.com.au/api/my-garage/ridereveal/generate/" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "garage_vehicle_id": "<GARAGE_VEHICLE_UUID>",
    "first_name": "Stephen",
    "custom_plate": "WE323",
    "favorite_color": "Midnight Blue"
  }'
```

The result response (both `GET .../result/<garage_vehicle_id>/` and the completed job poll `GET .../job/<job_id>/`) now includes the persisted name:

```json
{
  "first_name": "Stephen",
  "custom_plate": "WE323",
  "favorite_color": "Midnight Blue",
  ...
}
```

- `first_name` is `null` for reveals generated before this deploy; fall back to the account profile name as you do today.
- The share-card PNG uses `first_name` (reveal-time) first, then the account profile name.

### 4b. `share_image_url` is never null on a *completed* job anymore

Previously the job was marked `complete` before the PNG finished rendering, so a poll could return `status: "complete"` with `share_image_url: null`. Now the render finishes **before** completion is reported, so:

- When the job poll returns `status: "complete"`, `result.share_image_url` is **always** populated.
- The one-shot re-fetch after 4 s (section 2) is now only needed as a safety net for reveals generated before this deploy — keep it, but it should rarely trigger.
- The `null` case now only happens if Chromium rendering genuinely failed (permanent for that reveal) → text fallback, as before.
