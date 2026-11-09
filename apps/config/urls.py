from django.urls import path
from .views import SiteConfigView


urlpatterns = [
    # Canonical: /api/config/ (the project include already carries the
    # api/config/ prefix). Aliases keep older call shapes alive.
    path('', SiteConfigView.as_view(), name='site-config'),
    path('site-config/', SiteConfigView.as_view(), name='site-config-alias'),
    path('api/config/', SiteConfigView.as_view(), name='site-config-legacy'),
]
