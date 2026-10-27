"""Vehicle image-quality services.

- Grok (xAI) vision classification of vehicle images (OpenAI-compatible API).
- Pure-Pillow heuristic pre-screen for obvious placeholders / silhouettes.
- Wikimedia Commons search/download helpers shared by management commands.
- Domain blacklist enforcement for image scraping.

No network calls happen at import time; all requests are made inside the
functions below.
"""
import base64
import json
import logging
import os
import time
import uuid
from urllib.parse import unquote, urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "CarrebBot/1.0 (carreb.com.au; dev@carreb.com.au)"

# TODO: support press-portal sources (OEM media kits) once licensing is sorted.
# Only freely licensed sources (Wikimedia Commons) are allowlisted for now.
BLACKLISTED_DOMAINS = (
    "carsales.com.au",
    "redbook.com.au",
    "carexpert.com.au",
    "carsguide.com.au",
    "autotrader.com.au",
    "drive.com.au",
    "glassguide.com.au",
)

GROK_API_KEY = getattr(settings, "GROK_API_KEY", os.environ.get("GROK_API_KEY", ""))
XAI_BASE_URL = getattr(settings, "XAI_BASE_URL", "https://api.x.ai/v1")
XAI_VISION_MODEL = getattr(settings, "XAI_VISION_MODEL", "grok-2-vision-1212")

VERDICT_MAP = {
    "real_photo": "real_photo",
    "silhouette": "silhouette",
    "illustration_render": "illustration",
    "logo_badge": "logo",
    "placeholder_empty": "placeholder",
}

CLASSIFY_PROMPT = """You are a strict image-quality classifier for a vehicle marketplace database.
Look at the provided image and classify it into EXACTLY ONE of these categories:
- real_photo: a genuine photograph of a real car (showroom, street, press photo of the actual vehicle).
- silhouette: a flat single-colour vehicle outline/shadow graphic, typically on a plain background.
- illustration_render: a drawing, vector artwork, 3D render, or artistic impression of a car.
- logo_badge: a manufacturer badge, logo, emblem, or text-only graphic (not a full vehicle).
- placeholder_empty: a blank, broken-image, "coming soon", or otherwise empty placeholder.

Respond with ONLY a valid JSON object, no markdown fences, no extra text:
{"verdict": "<one of real_photo|silhouette|illustration_render|logo_badge|placeholder_empty>", "reason": "<one short sentence>"}"""


class ImageAIError(Exception):
    """Raised when the Grok vision call fails for any reason (auth, credits, network, bad response)."""


def xai_client():
    """Return an OpenAI-compatible client pointed at the xAI API."""
    import openai

    return openai.OpenAI(
        api_key=GROK_API_KEY,
        base_url=XAI_BASE_URL,
        timeout=30,
    )


def _detect_mime(image_bytes: bytes) -> str:
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/png"  # default; Grok servers sniff content anyway


def classify_image(image_bytes: bytes) -> dict:
    """Classify a vehicle image with Grok vision.

    Returns {"verdict": "real_photo"|"silhouette"|"illustration"|"logo"|"placeholder",
             "reason": str, "raw_verdict": str}.
    Raises ImageAIError on any API/parse failure — callers must handle it.
    """
    if not GROK_API_KEY:
        raise ImageAIError("GROK_API_KEY is not configured")

    mime = _detect_mime(image_bytes)
    data_url = "data:{};base64,{}".format(
        mime, base64.b64encode(image_bytes).decode("ascii")
    )

    client = xai_client()
    try:
        response = client.chat.completions.create(
            model=XAI_VISION_MODEL,
            messages=[
                {"role": "system", "content": "You respond only with valid JSON."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": CLASSIFY_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            response_format={"type": "json_object"},
            timeout=30,
        )
        content = response.choices[0].message.content
    except Exception as e:
        raise ImageAIError(f"xAI vision call failed: {e}") from e

    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError) as e:
        raise ImageAIError(f"xAI returned unparseable JSON: {content!r}") from e

    raw_verdict = str(parsed.get("verdict", "")).strip().lower()
    verdict = VERDICT_MAP.get(raw_verdict)
    if verdict is None:
        raise ImageAIError(f"xAI returned unknown verdict: {raw_verdict!r}")
    return {
        "verdict": verdict,
        "reason": str(parsed.get("reason", "")),
        "raw_verdict": raw_verdict,
    }


def heuristic_check(image_bytes) -> dict | None:
    """Fast pure-Pillow pre-screen. Returns {"verdict": "placeholder"|"silhouette",
    "detail": str} when clearly bad, else None (inconclusive). Never throws."""
    if image_bytes is None:
        return {"verdict": "placeholder", "detail": "no image data"}
    size = len(image_bytes)
    if size < 6 * 1024:
        return {"verdict": "placeholder", "detail": f"file too small ({size} bytes < 6KB)"}

    try:
        from PIL import Image

        with Image.open(__import__("io").BytesIO(image_bytes)) as im:
            im.load()
            width, height = im.size
            if width < 400 or height < 250:
                return {
                    "verdict": "placeholder",
                    "detail": f"dimensions too small ({width}x{height})",
                }

            has_alpha = im.mode in ("RGBA", "LA") or (
                im.mode == "P" and "transparency" in im.info
            )
            if has_alpha:
                rgba = im.convert("RGBA")
                total = rgba.width * rgba.height
                if total:
                    transparent = sum(
                        1 for a in rgba.getchannel("A").getdata() if a == 0
                    )
                    if transparent / total >= 0.40:
                        return {
                            "verdict": "silhouette",
                            "detail": f"{transparent / total:.0%} fully transparent pixels",
                        }

            small = im.convert("RGB").resize((32, 32))
            colors = set()
            for r, g, b in small.getdata():
                # Exclude near-white / near-black background colours from the count.
                if r > 240 and g > 240 and b > 240:
                    continue
                if r < 15 and g < 15 and b < 15:
                    continue
                colors.add((r // 16, g // 16, b // 16))
            if len(colors) <= 6:
                return {
                    "verdict": "silhouette",
                    "detail": f"only {len(colors)} distinct colours after downscale",
                }
    except Exception as e:
        return {"verdict": "placeholder", "detail": f"undecodable image: {e}"}

    return None


# ---------------------------------------------------------------------------
# Blacklist
# ---------------------------------------------------------------------------

def is_blacklisted(url: str) -> bool:
    """True when the URL's host (or any parent domain) is on the blacklist."""
    if not url:
        return False
    try:
        host = urlparse(url if "//" in url else "//" + url).hostname or ""
    except ValueError:
        return False
    host = host.lower()
    for domain in BLACKLISTED_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return True
    return False


# ---------------------------------------------------------------------------
# Wikimedia Commons helpers (shared by fetch_vehicle_images and scrape_vehicle_images)
# ---------------------------------------------------------------------------

def find_commons_image(query: str, headers: dict | None = None,
                       delay: float = 0.0, log=logger,
                       thumb_width: int = 1200) -> str:
    """Return the URL of the first Wikimedia Commons image matching the query, or ''.

    Returns a ``Special:FilePath`` thumbnail URL (width=1200) rather than the
    original — Commons throttles original-resolution downloads per IP (429).
    """
    headers = headers or {"User-Agent": USER_AGENT}
    if delay:
        time.sleep(delay)
    search_params = {
        "action": "query",
        "generator": "search",
        "gsrnamespace": 6,
        "gsrsearch": query,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "format": "json",
        "origin": "*",
    }
    try:
        r = requests.get(WIKIMEDIA_API, params=search_params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("Commons search error: %s", e)
        return ""

    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return ""

    for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        imageinfo = page.get("imageinfo")
        if not imageinfo:
            continue
        title = page.get("title", "")            # "File:Name.jpg"
        if title.lower().startswith("file:"):
            filename = title[5:]
            return (f"https://commons.wikimedia.org/wiki/Special:FilePath/"
                    f"{filename}?width={thumb_width}")
        url = imageinfo[0].get("url")
        if url:
            return url
    return ""


def download_image(url: str, out_dir: str, headers: dict | None = None,
                   delay: float = 0.0, log=logger,
                   max_retries: int = 2) -> str:
    """Download image to out_dir, return local file path or ''.

    Uses the same uuid-based naming scheme across all commands. On HTTP 429
    (rate limited) backs off exponentially and retries."""
    headers = headers or {"User-Agent": USER_AGENT}
    ext = os.path.splitext(unquote(url).split("?")[0])[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"

    filename = f"{uuid.uuid4().hex}{ext}"
    local_path = os.path.join(out_dir, filename)

    # Strip tracking query params before downloading; they cause 429s on upload.wikimedia.org.
    download_url = url.split("?")[0] if "wikimedia.org" not in url else url

    if delay:
        time.sleep(delay)
    for attempt in range(max_retries + 1):
        try:
            r = requests.get(download_url, headers=headers, timeout=30)
            r.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(r.content)
            return local_path
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429 and attempt < max_retries:
                wait = 15 * (attempt + 1)
                log.warning("429 rate-limited; backing off %ss", wait)
                time.sleep(wait)
                continue
            log.warning("Download error: %s", e)
            return ""
        except Exception as e:
            log.warning("Download error: %s", e)
            return ""
    return ""


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}
