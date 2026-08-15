from django.urls import path
from .views import SiteConfigView


urlpatterns = [
    path('api/config/', SiteConfigView.as_view(), name='site-config'),
]
