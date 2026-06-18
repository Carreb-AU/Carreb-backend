from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from .serializers import WaitlistSubmitSerializer, PrelaunchStatusSerializer
from .services import submit_waitlist_email
from .selectors import get_prelaunch_status

class WaitlistSubmitView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = WaitlistSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data.get('email')
        source = serializer.validated_data.get('source')
        
        submit_waitlist_email(email=email, source=source)
        
        return Response(
            {"message": "Your email is saved. You will be notified when the full site launches."},
            status=status.HTTP_200_OK
        )

class PrelaunchStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        status_data = get_prelaunch_status()
        serializer = PrelaunchStatusSerializer(status_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

