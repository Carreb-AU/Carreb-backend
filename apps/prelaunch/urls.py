from django.urls import path
from .views import WaitlistSubmitView, PrelaunchStatusView

urlpatterns = [
    path('waitlist/', WaitlistSubmitView.as_view(), name='waitlist-submit'),
    path('prelaunch/status/', PrelaunchStatusView.as_view(), name='prelaunch-status'),
]
