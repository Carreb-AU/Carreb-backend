from rest_framework import views
from rest_framework.response import Response
from .models import SiteConfig
from .serializers import SiteConfigSerializer


class SiteConfigView(views.APIView):
    """Public endpoint returning the current site configuration."""

    permission_classes = []
    authentication_classes = []

    def get(self, request):
        config = SiteConfig.get()
        serializer = SiteConfigSerializer(config)
        return Response(serializer.data)
