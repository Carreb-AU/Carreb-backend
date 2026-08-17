"""On-demand vehicle image lookup via Wikimedia Commons.

Used by search/type-ahead views so images are fetched only when a vehicle is
actually returned to a user, instead of pre-downloading tens of thousands of
images to local storage.

When Commons has no match, we fall back to an FCAI vehicle silhouette
appropriate for the vehicle's category and body style.
"""
import logging
import time
from functools import lru_cache
from typing import Optional

import requests
from django.conf import settings
from django.core.cache import cache

from apps.vehicles.services.silhouette_lookup import get_silhouette_url

logger = logging.getLogger(__name__)

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "CarrebBot/1.0 (carreb.com.au; dev@carreb.com.au)"
DEFAULT_FALLBACK = "https://carreb-developement.vercel.app/assets/Images/car.png"
CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _fallback_url() -> str:
    return getattr(settings, "VEHICLE_IMAGE_FALLBACK_URL", DEFAULT_FALLBACK)


def _cache_key(make: str, model: str) -> str:
    safe_make = (make or "").lower().replace(" ", "_")
    safe_model = (model or "").lower().replace(" ", "_")
    return f"vehicle:image_url:{safe_make}:{safe_model}"


def _find_commons_image(query: str, delay: float = 0.25) -> str:
    """Return the URL of the first Wikimedia Commons image matching the query."""
    time.sleep(delay)
    params = {
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
        r = requests.get(
            WIKIMEDIA_API,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning("Wikimedia Commons search failed for %r: %s", query, exc)
        return ""

    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return ""

    for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        imageinfo = page.get("imageinfo")
        if not imageinfo:
            continue
        url = imageinfo[0].get("url")
        if url:
            # Strip any tracking query params.
            return url.split("?")[0]
    return ""


def get_vehicle_image_url(
    make: str,
    model: str,
    year: int | None = None,
    fcai_category: Optional[str] = None,
    body_style: Optional[str] = None,
    drive: Optional[str] = None,
    delay: float = 0.25,
) -> str:
    """Return an image URL for a vehicle, fetching from Commons on cache miss.

    The result is cached for 30 days.  If no Commons image is found, we fall
    back to an FCAI silhouette matched on ``fcai_category`` and
    ``body_style``.  The negative result is also cached for 24 hours so we
    don't keep hitting the API for the same missing vehicle.
    """
    make = (make or "").strip()
    model = (model or "").strip()
    if not make and not model:
        return get_silhouette_url(fcai_category, body_style, drive)

    key = _cache_key(make, model)
    cached = cache.get(key)
    if cached is not None:
        # If the cached value is the old generic fallback, replace it with a
        # silhouette when we now have category/body-style info.
        if cached == _fallback_url():
            silhouette = get_silhouette_url(fcai_category, body_style, drive)
            if silhouette != cached:
                cache.set(key, silhouette, CACHE_TTL_SECONDS)
                return silhouette
        return cached

    query = f"{make} {model}".strip()
    if year:
        query = f"{year} {query}"

    url = _find_commons_image(query, delay=delay)
    if url:
        cache.set(key, url, CACHE_TTL_SECONDS)
        return url

    # Cache the silhouette fallback for 24 hours.
    fallback = get_silhouette_url(fcai_category, body_style, drive)
    cache.set(key, fallback, 60 * 60 * 24)
    return fallback


def warm_vehicle_image_cache(make: str, model: str, year: int | None = None) -> str:
    """Explicitly warm the cache for a known vehicle."""
    return get_vehicle_image_url(make, model, year=year)
