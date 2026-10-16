"""CORE Dial endpoints (v6.4).

GET /api/core-dial/dataset/?state=NSW   — every on-sale listing in the state,
                                        cut to its Mode B row. No vehicle names.
                                        Free users get it too (locked Dial still
                                        shows COO and CO2). ETag from
                                        scoring_version + state; Cache-Control: private.
GET /api/core-dial-matches/             — the green button. Paid plans only,
                                        "search"-scoped throttle 20/min.
"""
from django.http import HttpResponseNotModified
from rest_framework import views, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.users.models import SubscriptionTier
from apps.vehicles.models import CoreDialBatch, CoreDialRow
from apps.vehicles.services.core_dial import (
    AU_STATES,
    compute_bands,
    is_valid_budget,
    matches_header,
    select_matches,
)


class SearchRateThrottle(UserRateThrottle):
    """Scoped "search" rate: 20/min (spec section 7)."""
    scope = 'search'


def _current_batch():
    return CoreDialBatch.objects.filter(is_current=True).first()


def _row_to_dataset_dict(r):
    return {
        'version_id': r.version_id,
        'model_id': r.model_id,
        'driveaway_cents': r.driveaway_cents,
        'coo_pa_cents': r.coo_pa_cents,
        'annual_co2_kg': r.annual_co2_kg,
        'price_score': r.price_score,
        'emissions_score': r.emissions_score,
        'co2_cap': r.co2_cap,
        'parts_cents': r.parts_cents,
    }


class CoreDialDatasetView(views.APIView):
    """The Dial dataset — one fetch per state, never on a slider move."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        state = (request.query_params.get('state') or '').upper()
        if state not in AU_STATES:
            return Response({'error': 'invalid_params'}, status=status.HTTP_400_BAD_REQUEST)

        batch = _current_batch()
        if batch is None:
            return Response({'error': 'no_dataset'}, status=status.HTTP_404_NOT_FOUND)

        etag = f'"{batch.scoring_version}:{state}"'
        # GZipMiddleware (and nginx/Cloudflare) weaken strong ETags to
        # W/"..." — accept both forms on the way back in.
        if_none_match = (request.META.get('HTTP_IF_NONE_MATCH') or '').strip()
        if if_none_match.removeprefix('W/') == etag:
            return HttpResponseNotModified()

        rows = (
            CoreDialRow.objects
            .filter(batch=batch, state=state)
            .order_by('version_id')
        )
        payload = {
            'scoring_version': batch.scoring_version,
            'state': state,
            'as_at': batch.as_at.isoformat() if batch.as_at else None,
            'rows': [_row_to_dataset_dict(r) for r in rows],
        }
        response = Response(payload)
        response.headers['ETag'] = etag
        response.headers['Cache-Control'] = 'private'
        return response


class CoreDialMatchesView(views.APIView):
    """The green button — "View [band]™ vehicles". Paid plans only."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [SearchRateThrottle]

    def get(self, request):
        if request.user.subscription_tier == SubscriptionTier.FREE:
            return Response({'error': 'upgrade_required'}, status=status.HTTP_403_FORBIDDEN)

        params = request.query_params
        state = (params.get('state') or '').upper()
        budget = params.get('budget')
        stop = params.get('stop')
        band = params.get('band')
        version = params.get('v')

        # All five params required and validated (400 invalid_params).
        try:
            budget = int(budget)
        except (TypeError, ValueError):
            budget = None
        try:
            stop = int(stop)
        except (TypeError, ValueError):
            stop = None
        try:
            band = int(band)
        except (TypeError, ValueError):
            band = None

        if (state not in AU_STATES or not is_valid_budget(budget)
                or stop not in range(1, 6) or band not in range(1, 6)
                or not version):
            return Response({'error': 'invalid_params'}, status=status.HTTP_400_BAD_REQUEST)

        batch = _current_batch()
        if batch is None:
            return Response({'error': 'no_dataset'}, status=status.HTTP_404_NOT_FOUND)
        if version != batch.scoring_version:
            return Response(
                {'error': 'dataset_stale', 'scoring_version': batch.scoring_version},
                status=status.HTTP_409_CONFLICT,
            )

        rows = CoreDialRow.objects.filter(batch=batch, state=state)
        bands = compute_bands(rows, budget, stop)
        band_data = bands[band]

        picked = select_matches(band_data['models'], limit=10)
        results = []
        for m in picked:
            r = m['row']
            vehicle = r.vehicle
            results.append({
                'vehicle_id': str(vehicle.id) if vehicle else str(r.id),
                'year': r.year,
                'make': r.make,
                'model': r.model,
                'variant': r.variant,
                'rating': m['rating'],
                'band': band,
                'co2_g_km': int(r.co2_g_per_km or 0),
                'driveaway_cents': r.driveaway_cents,
                'coo_pa_cents': r.coo_pa_cents,
                'price_basis': getattr(vehicle, 'price_basis', '') or '',
                'image_url': getattr(vehicle, 'image_url', None) or None,
            })

        total = band_data['count']
        return Response({
            'scoring_version': batch.scoring_version,
            'total': total,
            'shown': len(results),
            'header': matches_header(total, len(results)),
            'results': results,
        })
