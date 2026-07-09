import logging
from rest_framework import views, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from apps.mygarage.models import GarageVehicle, DealerSearchLog
from apps.mygarage.serializers import FindDealerRequestSerializer, DealerLinkClickedSerializer
from apps.mygarage.services import get_dealers, BRAND_LOCATORS
from apps.vehicles.tasks import emit_analytics_event

logger = logging.getLogger(__name__)

DISCLAIMER_TEXT = (
    "Dealer information sourced from public listings. "
    "Carreb is independent — we don't earn commissions "
    "from dealers or manufacturers."
)

class FindDealerThrottle(UserRateThrottle):
    scope = 'find_a_dealer'

class FindDealerView(views.APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [FindDealerThrottle]

    def post(self, request, *args, **kwargs):
        serializer = FindDealerRequestSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            if 'postcode' in errors:
                return Response({
                    "error": "invalid_postcode",
                    "message": "Please enter a valid 4-digit Australian postcode."
                }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            if 'radius_km' in errors:
                return Response({
                    "error": "invalid_radius",
                    "message": "Radius must be 5, 25, 50, or 100 km."
                }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        garage_vehicle_id = serializer.validated_data['garage_vehicle_id']
        postcode = serializer.validated_data['postcode']
        radius_km = serializer.validated_data['radius_km']

        try:
            garage_vehicle = GarageVehicle.objects.select_related('vehicle_catalogue').get(
                id=garage_vehicle_id, 
                user=request.user
            )
        except GarageVehicle.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        brand = garage_vehicle.vehicle_catalogue.brand

        res = get_dealers(brand, postcode, radius_km)

        results_count = len(res.get('results', []))
        
        DealerSearchLog.objects.create(
            user=request.user,
            vehicle_brand=brand,
            postcode=postcode,
            radius_km=radius_km,
            results_count=results_count
        )

        if getattr(request.user, 'analytics_consent', False):
            emit_analytics_event.delay(
                str(request.user.id),
                'find_dealer_searched',
                {'brand': brand, 'radius_km': radius_km}
            )

        if res.get('service_unavailable'):
            return Response({
                "results": [],
                "service_unavailable": True,
                "message": "Dealer search is temporarily unavailable. Please try again shortly.",
                "disclaimer": DISCLAIMER_TEXT
            }, status=status.HTTP_200_OK)

        results = res.get('results', [])
        
        from django.utils.text import slugify
        brand_slug = slugify(brand)
        fallback_url = BRAND_LOCATORS.get(brand_slug, f"https://www.google.com.au/search?q={brand_slug}+dealer+australia")

        if results_count == 0:
            return Response({
                "vehicle_brand": brand,
                "search_postcode": postcode,
                "search_radius_km": radius_km,
                "results": [],
                "no_results_message": f"No {brand} dealers found within {radius_km}km of the {postcode} area. Try expanding your search radius.",
                "brand_locator_fallback_url": fallback_url,
                "disclaimer": DISCLAIMER_TEXT
            }, status=status.HTTP_200_OK)

        return Response({
            "vehicle_brand": brand,
            "search_postcode": postcode,
            "search_radius_km": radius_km,
            "results": results,
            "brand_locator_fallback_url": fallback_url,
            "disclaimer": DISCLAIMER_TEXT
        }, status=status.HTTP_200_OK)


class DealerLinkClickedAnalyticsView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = DealerLinkClickedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vehicle_brand = serializer.validated_data['vehicle_brand']

        if getattr(request.user, 'analytics_consent', False):
            emit_analytics_event.delay(
                str(request.user.id),
                'outbound_dealer_link_clicked',
                {'vehicle_brand': vehicle_brand}
            )

        return Response(status=status.HTTP_200_OK)
