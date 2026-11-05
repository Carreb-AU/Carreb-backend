"""RideReveal share-card rendering.

Fills templates/share/ride_reveal_share_card.html from a RideRevealResult and
screenshots the .card element with headless Chromium (Playwright) to a
1080 x 1350 PNG stored on the result's share_image field. Frontend shares
that PNG plus the profile link (see rideRevealShareCardHtml.js spec).

Any failure here is logged and swallowed — the reveal itself never breaks;
the frontend falls back to link-only sharing when share_image is absent.
"""
import logging
import os

from django.conf import settings
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

CARD_WIDTH = 1080
CARD_HEIGHT = 1350

# Car-color name -> hex swatch, matched case-insensitively by substring.
COLOR_HEX = {
    'black': '#111111',
    'white': '#f4f4f4',
    'silver': '#c0c0c0',
    'grey': '#6b7280',
    'gray': '#6b7280',
    'red': '#b3001b',
    'rosso': '#b3001b',
    'blue': '#1a2744',
    'navy': '#1a2744',
    'green': '#2d5a3d',
    'yellow': '#f4c542',
    'gold': '#c8a24a',
    'orange': '#e07020',
    'bronze': '#8c6a3f',
    'brown': '#6b4a2f',
    'beige': '#d8c8a8',
    'purple': '#5b3a8c',
    'pink': '#e88bb0',
    'ivory': '#f2ead8',
    'pearl': '#eae6da',
    'charcoal': '#333333',
    'graphite': '#3a3f44',
    'champagne': '#e6d3a3',
}


def _absolute(url):
    if not url:
        return ''
    if url.startswith('http://') or url.startswith('https://'):
        return url
    if url.startswith('/'):
        base = getattr(settings, 'API_BASE_URL', 'https://api.carreb.com.au')
        return base.rstrip('/') + url
    return url


# Plate header states the user's state, never a hardcoded one (B-16: a QLD
# user was shown "WESTERN AUSTRALIA").
PLATE_STATE_NAMES = {
    'NSW': 'NEW SOUTH WALES',
    'VIC': 'VICTORIA',
    'QLD': 'QUEENSLAND',
    'SA': 'SOUTH AUSTRALIA',
    'WA': 'WESTERN AUSTRALIA',
    'TAS': 'TASMANIA',
    'NT': 'NORTHERN TERRITORY',
    'ACT': 'AUSTRALIAN CAPITAL TERRITORY',
}


def _plate_state_name(user):
    state = (getattr(getattr(user, 'priority_state', None), 'state', None) or '').upper()
    return PLATE_STATE_NAMES.get(state, '')


def _color_hex(label):
    text = (label or '').casefold()
    for name, hex_value in COLOR_HEX.items():
        if name in text:
            return hex_value
    return ''


def build_share_card_context(result):
    user = result.user
    vehicle = result.vehicle_catalogue
    display_name = (getattr(result, 'first_name', None) or user.first_name or '').strip() or 'You'
    traits = getattr(result, 'traits', None) or []
    return {
        'display_name': display_name,
        'avatar_initial': (display_name[0] or 'Y').upper(),
        'photo_url': _absolute(getattr(user, 'profile_photo_url', None)),
        'archetype_name': result.archetype_name,
        'archetype_tagline': result.archetype_tagline,
        'vehicle_image_url': _absolute(getattr(vehicle, 'image_url', None)),
        'license_plate': result.custom_plate or '',
        'plate_state': _plate_state_name(user),
        'favorite_color_hex': _color_hex(result.favorite_color),
        'favorite_color_label': result.favorite_color or '',
        'traits': list(traits)[:5],
        'self_insight_text': result.self_insight_text,
        'social_perception_text': result.social_perception_text,
        'did_you_know_fact': result.did_you_know_fact,
    }


def render_share_card_html(result):
    return render_to_string(
        'share/ride_reveal_share_card.html',
        build_share_card_context(result),
    )


def generate_share_card_png(result):
    """Render + screenshot the share card onto result.share_image.

    Returns True on success, False otherwise. Never raises.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning('ride reveal share card: playwright not installed')
        return False

    try:
        html = render_share_card_html(result)
        out_dir = os.path.join(settings.MEDIA_ROOT, 'ride_reveal_shares')
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f'{result.id}.png')

        with sync_playwright() as p:
            # --no-sandbox: standard for Chromium inside Docker containers
            # (no usable user-namespace sandbox); we render only our own
            # static template, so the sandbox buys nothing here.
            browser = p.chromium.launch(args=['--no-sandbox'])
            try:
                page = browser.new_page(
                    viewport={'width': CARD_WIDTH, 'height': CARD_HEIGHT})
                page.set_content(html, wait_until='networkidle')
                page.locator('.card').screenshot(path=path)
            finally:
                browser.close()

        result.share_image.name = f'ride_reveal_shares/{result.id}.png'
        result.save(update_fields=['share_image'])
        logger.info('ride reveal share card rendered: %s', result.id)
        return True
    except Exception:
        logger.exception('ride reveal share card rendering failed: %s', result.id)
        return False
