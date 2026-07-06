from django.urls import path

from apps.freematch.views import (
    FreeMatchCalculateView,
    FreeMatchSaveView,
    FreeMatchDiscardView,
)

urlpatterns = [
    # 1. Single API payload to calculate match
    path(
        "api/free-match/calculate/",
        FreeMatchCalculateView.as_view(),
        name="free-match-calculate",
    ),
    # 2. Save result to MyGarage after account creation (auth required)
    path(
        "api/free-match/<str:session_token>/save/",
        FreeMatchSaveView.as_view(),
        name="free-match-save",
    ),
    # 3. Discard session — permanently deletes all wizard data (no auth)
    path(
        "api/free-match/<str:session_token>/",
        FreeMatchDiscardView.as_view(),
        name="free-match-discard",
    ),
]
