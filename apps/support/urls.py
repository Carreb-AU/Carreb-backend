from django.urls import path
from .views import (
    ContactUsAPIView,
    GetInTouchAPIView,
    BugReportAPIView,
    FeatureSuggestionAPIView,
    RateLimitStatusAPIView,
    PrefillAPIView
)

urlpatterns = [
    path('contact/', ContactUsAPIView.as_view(), name='contact_us'),
    path('get-in-touch/', GetInTouchAPIView.as_view(), name='get_in_touch'),
    path('bug-report/', BugReportAPIView.as_view(), name='bug_report'),
    path('feature-suggestion/', FeatureSuggestionAPIView.as_view(), name='feature_suggestion'),
    path('rate-limit-status/', RateLimitStatusAPIView.as_view(), name='rate_limit_status'),
    path('prefill/', PrefillAPIView.as_view(), name='prefill'),
]
