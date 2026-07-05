from django.urls import path

from apps.freematch.views import (
    FreeMatchStartView,
    FreeMatchStepView,
    FreeMatchCalculateView,
    FreeMatchSaveView,
    FreeMatchDiscardView,
)

urlpatterns = [
    # 1. Start a new wizard session (no auth)
    path(
        "api/free-match/start/",
        FreeMatchStartView.as_view(),
        name="free-match-start",
    ),
    # 2. Submit an answer for a single wizard step (no auth)
    path(
        "api/free-match/<str:session_token>/step/",
        FreeMatchStepView.as_view(),
        name="free-match-step",
    ),
    # 3. Trigger vehicle match calculation (no auth)
    path(
        "api/free-match/<str:session_token>/match/",
        FreeMatchCalculateView.as_view(),
        name="free-match-calculate",
    ),
    # 4. Save result to MyGarage after account creation (auth required)
    path(
        "api/free-match/<str:session_token>/save/",
        FreeMatchSaveView.as_view(),
        name="free-match-save",
    ),
    # 5. Discard session — permanently deletes all wizard data (no auth)
    path(
        "api/free-match/<str:session_token>/",
        FreeMatchDiscardView.as_view(),
        name="free-match-discard",
    ),
]
