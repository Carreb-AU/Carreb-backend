import logging

from rest_framework import status, views
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.freematch.selectors import get_freematch_session
from apps.freematch.serializers import FreeMatchCalculateSerializer
from apps.freematch.services import (
    build_unlocked_response,
    process_free_match,
    convert_session_to_garage,
    discard_freematch_session,
)
from apps.mygarage.services import check_cap_limit, get_cap_counter
from apps.vehicles.tasks import emit_analytics_event

logger = logging.getLogger(__name__)


def _get_session_or_error(session_token: str):
    """
    Returns (session, None) if valid, or (None, Response) if not found / expired.
    Caller must return the Response immediately when session is None.
    """
    session = get_freematch_session(session_token)
    if not session:
        return None, Response(
            {"detail": "Wizard session not found.", "field": "session_token"},
            status=status.HTTP_404_NOT_FOUND,
        )

    if session.is_expired:
        return None, Response(
            {
                "detail": (
                    "This wizard session has expired. "
                    "Please start a new session to continue."
                ),
                "expired": True,
            },
            status=status.HTTP_410_GONE,
        )

    return session, None


class FreeMatchCalculateView(views.APIView):
    """
    POST /api/free-match/calculate/

    Receives the entire Free Match payload, creates the session, 
    calculates the match, and returns the partial result with gated fields.
    """
    permission_classes = [AllowAny]
    throttle_scope = "anon"

    def post(self, request):
        serializer = FreeMatchCalculateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": "Invalid payload.", "errors": serializer.errors},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        payload = serializer.validated_data

        try:
            response_data = process_free_match(payload)
            session_token = response_data.get("session_token")
            
            # Re-fetch session to get ID for analytics
            session = get_freematch_session(session_token)
            if session:
                emit_analytics_event.delay(
                    str(session.id),
                    "free_match_wizard_calculated",
                    {},
                )
                emit_analytics_event.delay(
                    str(session.id),
                    "free_match_result_viewed",
                    {},
                )

            return Response(response_data, status=status.HTTP_200_OK)

        except RuntimeError as exc:
            logger.error("Free match wizard match failure: %s", exc)
            return Response(
                {"detail": "Match service temporarily unavailable. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            logger.exception("Unexpected error during free match wizard match")
            return Response(
                {"detail": "Match service temporarily unavailable. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class FreeMatchSaveView(views.APIView):
    """
    POST /api/free-match/{session_token}/save/

    Requires authentication (visitor has just registered).
    Saves the matched vehicle to the new user's MyGarage and unlocks
    all gated fields.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, session_token):
        session, err = _get_session_or_error(session_token)
        if err:
            return err

        if not session.matched_vehicle_id:
            return Response(
                {"detail": "No match has been calculated for this session yet."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if session.converted_user_id:
            return Response(
                {"detail": "This session has already been saved to a garage."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user

        if not check_cap_limit(user):
            cap = get_cap_counter(user)
            return Response(
                {
                    "detail": (
                        f"Your garage is full. You are on {cap['plan']} which allows "
                        f"{cap['limit']} vehicle(s). Upgrade to add more."
                    ),
                    "cap_counter": cap,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        garage_vehicle = convert_session_to_garage(session, user)

        if getattr(user, "analytics_consent", False):
            emit_analytics_event.delay(
                str(user.id),
                "free_match_converted",
                {},
            )
            emit_analytics_event.delay(
                str(user.id),
                "vehicle_added_to_garage",
                {"source": "free_match_wizard"},
            )

        response_data = build_unlocked_response(
            vehicle=session.matched_vehicle,
            user=user,
            garage_vehicle=garage_vehicle,
        )

        return Response(response_data, status=status.HTTP_200_OK)


class FreeMatchDiscardView(views.APIView):
    """
    DELETE /api/free-match/{session_token}/

    Immediately and permanently deletes the FreeMatchSession.
    """
    permission_classes = [AllowAny]
    throttle_scope = "anon"

    def delete(self, request, session_token):
        session = get_freematch_session(session_token)
        if not session:
            return Response({"discarded": True}, status=status.HTTP_200_OK)

        emit_analytics_event.delay(
            str(session.id),
            "free_match_discarded",
            {},
        )

        discard_freematch_session(session)

        return Response({"discarded": True}, status=status.HTTP_200_OK)
