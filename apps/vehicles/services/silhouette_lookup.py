"""FCAI vehicle-silhouette fallback images.

The silhouette assets live in:
    docs/Tier 3 Images - FCAI Vehicle Silhouette Images NEW CARS/

Run ``python manage.py collect_vehicle_silhouettes`` to copy them into
MEDIA_ROOT/vehicle_silhouettes/ with normalised filenames.  This service then
maps a vehicle's FCAI category + body style to the most appropriate silhouette.
"""
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_DIR = os.path.join(
    settings.BASE_DIR,
    "docs",
    "Tier 3 Images - FCAI Vehicle Silhouette Images NEW CARS",
)

MEDIA_SUBDIR = "vehicle_silhouettes"


def _silhouette_media_url(filename: str) -> str:
    base = settings.MEDIA_URL.rstrip("/")
    return f"{base}/{MEDIA_SUBDIR}/{filename}"


def _generic_fallback_url() -> str:
    return getattr(
        settings,
        "VEHICLE_IMAGE_FALLBACK_URL",
        "https://carreb-developement.vercel.app/assets/Images/car.png",
    )


def normalize_filename(name: str) -> str:
    """Normalise an original silhouette filename to a URL-safe slug.

    Examples:
        "Medium Category Sedan.png" -> "medium-category-sedan.png"
        "Pick-up _ Chassis 4x4 — Utility _ Pick-up.png" -> "pick-up-chassis-4x4-utility-pick-up.png"
        "Vans _ CC ≤ 2.5t — Blind_Window Van.png" -> "vans-cc-2-5t-blind-window-van.png"
    """
    # Drop extension.
    base = os.path.splitext(name)[0]
    # Lowercase.
    base = base.lower()
    # Replace common separators and punctuation with hyphens.
    base = re.sub(r"[\s_/,—–()]+", "-", base)
    # Replace the ≤ symbol with "-lt-" (less than) and remove stray special chars.
    base = base.replace("≤", "-lt-")
    base = re.sub(r"[^a-z0-9\.\-]+", "-", base)
    # Remove duplicate hyphens and trailing/leading hyphens.
    base = re.sub(r"-+", "-", base).strip("-")
    # Collapse version numbers like 2-5-3-5t -> 2-5-3-5t is fine, but 2-5t -> 2-5t.
    return f"{base}.png"


# Mapping from (fcai_category, body_style) to normalised silhouette filename.
# Category and body_style are matched case-insensitively.
SILHOUETTE_MAP = {
    # Micro
    ("micro", "sedan"): "micro-category-sedan.png",
    ("micro", "hatchback"): "micro-hatch.png",
    ("micro", "wagon"): "micro-category-wagon.png",
    # Light
    ("light", "sedan"): "light-category-sedan.png",
    ("light", "hatchback"): "light-category-hatch.png",
    ("light", "wagon"): "light-category-wagon.png",
    # Small
    ("small", "sedan"): "small-category-sedan.png",
    ("small", "hatchback"): "small-category-hatch.png",
    ("small", "wagon"): "small-category-wagon.png",
    # Medium
    ("medium", "sedan"): "medium-category-sedan.png",
    ("medium", "hatchback"): "medium-category-hatch.png",
    ("medium", "wagon"): "medium-category-wagon.png",
    # Large
    ("large", "sedan"): "large-category-sedan.png",
    ("large", "hatchback"): "large-category-hatch.png",
    ("large", "wagon"): "large-category-wagon.png",
    # Upper Large
    ("upper large", "sedan"): "upper-large-category-sedan.png",
    ("upper large", "hatchback"): "upper-large-category-hatch.png",
    ("upper large", "wagon"): "upper-large-category-wagon.png",
    # SUVs (FCAI category often contains "SUV")
    ("suv small", "suv"): "small-suv.png",
    ("small", "suv"): "small-suv.png",
    ("suv medium", "suv"): "medium-suv.png",
    ("medium", "suv"): "medium-suv.png",
    ("suv large", "suv"): "large-suv.png",
    ("large", "suv"): "large-suv.png",
    ("suv upper large", "suv"): "upper-large-suv.png",
    ("upper large", "suv"): "upper-large-suv.png",
    # Utes / pick-ups
    ("ute", "ute"): "pick-up-chassis-4x4-utility-pick-up.png",
    ("utility", "ute"): "pick-up-chassis-4x4-utility-pick-up.png",
    ("pick-up", "ute"): "pick-up-chassis-4x4-utility-pick-up.png",
    ("cab chassis", "cab chassis"): "pick-up-chassis-4x4-crew-cab.png",
    # Vans
    ("van", "van"): "vans-cc-lt-2.5t-blind-window-van.png",
    ("vans cc 2.5t", "van"): "vans-cc-lt-2.5t-blind-window-van.png",
    ("vans cc 2.5-3.5t", "van"): "vans-cc-2.5-3.5t-blind-window-van.png",
    ("vans cc 2.5-3.5t cab chassis", "cab chassis"): "vans-cc-2.5-3.5t-cab-chassis.png",
    # People movers / buses
    ("people mover", "people mover"): "people-movers.png",
    ("people-mover", "people mover"): "people-movers.png",
    ("light bus", "people mover"): "light-bus-20-seats-minibus.png",
    # Sports / convertibles
    ("sports", "coupe"): "sports-car-coupe.png",
    ("sports", "sports"): "sports-car-coupe.png",
    ("convertible", "convertible"): "convertible.png",
    ("roadster", "roadster"): "roadster.png",
    # Trucks (rare in consumer catalogue)
    ("medium duty", "truck"): "medium-duty-truck.png",
    ("heavy duty", "truck"): "heavy-duty-truck.png",
    ("heavy trucks light duty", "truck"): "heavy-trucks-light-duty.png",
}


def _normalise(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[\s_\-]+", " ", text)
    return text


def _key(fcai_category: str, body_style: str) -> tuple[str, str]:
    return (_normalise(fcai_category), _normalise(body_style))


def get_silhouette_url(
    fcai_category: Optional[str] = None,
    body_style: Optional[str] = None,
    drive: Optional[str] = None,
) -> str:
    """Return the URL of the best-matching FCAI silhouette, or the generic fallback."""
    category = _normalise(fcai_category)
    body = _normalise(body_style)

    if not category and not body:
        return _generic_fallback_url()

    filename = None

    # 1. Exact (category, body_style) match.
    filename = SILHOUETTE_MAP.get(_key(fcai_category or "", body_style or ""))

    # 2. Category-only fuzzy match.
    if not filename:
        for (cat, bod), mapped in SILHOUETTE_MAP.items():
            if cat == category and bod:
                filename = mapped
                break

    # 3. Body-style-only match.
    if not filename:
        for (cat, bod), mapped in SILHOUETTE_MAP.items():
            if bod == body:
                filename = mapped
                break

    if not filename:
        return _generic_fallback_url()

    # Silhouette files are copied to MEDIA_ROOT/vehicle_silhouettes by the
    # collect_vehicle_silhouettes command.  If the file does not exist yet,
    # return the generic fallback so we never serve a broken URL.
    dest_dir = Path(settings.MEDIA_ROOT) / MEDIA_SUBDIR
    if not (dest_dir / filename).exists():
        return _generic_fallback_url()

    return _silhouette_media_url(filename)


def collect_silhouettes(source_dir: str = DEFAULT_SOURCE_DIR) -> list[str]:
    """Copy normalised silhouette PNGs from source_dir to MEDIA_ROOT.

    Returns the list of copied normalised filenames.
    """
    source = Path(source_dir)
    dest = Path(settings.MEDIA_ROOT) / MEDIA_SUBDIR
    dest.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for src in source.glob("*.png"):
        normalised = normalize_filename(src.name)
        dst = dest / normalised
        shutil.copy2(src, dst)
        copied.append(normalised)

    return copied
