from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from rest_framework.exceptions import ValidationError

from .serializers import (
    ContactUsSerializer,
    GetInTouchSerializer,
    BugReportSerializer,
    FeatureSuggestionSerializer
)
from .services import create_support_ticket
from .rate_limit import (
    check_unauthenticated_rate_limit,
    check_authenticated_rate_limit,
    get_authenticated_rate_limit_status
)

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

class BaseSupportAPIView(APIView):
    def handle_exception(self, exc):
        if isinstance(exc, ValidationError):
            # Format validation errors as an array of { field, message }
            errors = []
            for field, messages in exc.detail.items():
                if isinstance(messages, list):
                    for msg in messages:
                        errors.append({"field": field, "message": str(msg)})
                else:
                    errors.append({"field": field, "message": str(messages)})
            return Response(errors, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return super().handle_exception(exc)

class ContactUsAPIView(BaseSupportAPIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        ip_address = get_client_ip(request)
        check_unauthenticated_rate_limit(ip_address)

        serializer = ContactUsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        create_support_ticket(
            ticket_type='contact_us',
            data=serializer.validated_data,
            user=None,
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        return Response({
            "submitted": True,
            "message": "Thank you — your message has been received."
        }, status=status.HTTP_200_OK)

class GetInTouchAPIView(BaseSupportAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        check_authenticated_rate_limit(request.user.id)

        serializer = GetInTouchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        create_support_ticket(
            ticket_type='get_in_touch',
            data=serializer.validated_data,
            user=request.user,
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        return Response({
            "submitted": True
        }, status=status.HTTP_200_OK)

class BugReportAPIView(BaseSupportAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        check_authenticated_rate_limit(request.user.id)

        serializer = BugReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        create_support_ticket(
            ticket_type='bug_report',
            data=serializer.validated_data,
            user=request.user,
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        return Response({
            "submitted": True
        }, status=status.HTTP_200_OK)

class FeatureSuggestionAPIView(BaseSupportAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        check_authenticated_rate_limit(request.user.id)

        serializer = FeatureSuggestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        create_support_ticket(
            ticket_type='feature_suggestion',
            data=serializer.validated_data,
            user=request.user,
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        return Response({
            "submitted": True
        }, status=status.HTTP_200_OK)

class RateLimitStatusAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        status_data = get_authenticated_rate_limit_status(request.user.id)
        return Response(status_data, status=status.HTTP_200_OK)

class PrefillAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        return Response({
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email
        }, status=status.HTTP_200_OK)
