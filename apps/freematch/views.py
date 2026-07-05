import logging

from rest_framework import status, views
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone

from apps.freematch.models import FreeMatchSession
from apps.freematch.serializers import (
    FreeMatchStepSerializer,
    Step1DataSerializer,
    Step2DataSerializer,
    Step3DataSerializer,
)
from apps.freematch.services import (
    build_match_response,
    build_unlocked_response,
    match_vehicle_for_wizard,
)
from apps.mygarage.models import GarageVehicle, GarageVehicleSource
from apps.mygarage.services import check_cap_limit, get_cap_counter
from apps.vehicles.tasks import emit_analytics_event

logger = logging.getLogger(__name__)



def _get_session_or_error(session_token: str):
    """
    Returns (session, None) if valid, or (None, Response) if not found / expired.
    Caller must return the Response immediately when session is None.
    """
    try:
        session = FreeMatchSession.objects.get(session_token=session_token)
    except FreeMatchSession.DoesNotExist:
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


class FreeMatchStartView(views.APIView):
    """
    POST /api/free-match/start/

    Creates a new FreeMatchSession and returns the session_token.
    No request body required.  No authentication required.
    """
    permission_classes = [AllowAny]
    throttle_scope = "anon"

    def post(self, request):
        session = FreeMatchSession.objects.create()

       
        emit_analytics_event.delay(
            str(session.id),
            "free_match_wizard_started",
            {},
        )

        return Response(
            {
                "session_token": session.session_token,
                "wizard_step": 1,
                "expires_at": session.expires_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )



class FreeMatchStepView(views.APIView):
    """
    PATCH /api/free-match/{session_token}/step/

    Accepts answers for a single wizard step and updates the session.
    Steps must be answered sequentially — no skipping allowed.
    """
    permission_classes = [AllowAny]
    throttle_scope = "anon"

    def patch(self, request, session_token):
        session, err = _get_session_or_error(session_token)
        if err:
            return err

      
        wrapper = FreeMatchStepSerializer(data=request.data)
        if not wrapper.is_valid():
            return Response(
                {"detail": "Invalid request.", "errors": wrapper.errors},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        step_number = wrapper.validated_data["step_number"]
        step_data = wrapper.validated_data["step_data"]

        expected_next = session.next_step
        if expected_next is not None and step_number != expected_next:
            return Response(
                {
                    "detail": (
                        f"Steps must be completed in order. "
                        f"Expected step {expected_next}, got {step_number}."
                    ),
                    "expected_step": expected_next,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        if step_number == 1:
            ser = Step1DataSerializer(data=step_data)
            if not ser.is_valid():
                return Response(
                    {"detail": "Invalid step 1 data.", "errors": ser.errors},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            session.has_current_vehicle = ser.validated_data["has_current_vehicle"]
            session.save(update_fields=["has_current_vehicle"])

        elif step_number == 2:
            if not session.step_2_required:
                return Response(
                    {
                        "detail": (
                            "Step 2 is not required because you indicated "
                            "you do not have a current vehicle. "
                            "Proceed to step 3."
                        )
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            ser = Step2DataSerializer(data=step_data)
            if not ser.is_valid():
                return Response(
                    {"detail": "Invalid step 2 data.", "errors": ser.errors},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            session.current_vehicle_make = ser.validated_data["current_vehicle_make"]
            session.current_vehicle_model = ser.validated_data["current_vehicle_model"]
            session.current_vehicle_year = ser.validated_data["current_vehicle_year"]
            session.save(
                update_fields=[
                    "current_vehicle_make",
                    "current_vehicle_model",
                    "current_vehicle_year",
                ]
            )

        elif step_number == 3:
            ser = Step3DataSerializer(data=step_data)
            if not ser.is_valid():
                return Response(
                    {"detail": "Invalid step 3 data.", "errors": ser.errors},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            session.fuel_type_preference = ser.validated_data["fuel_type_preference"]
            session.annual_km = ser.validated_data["annual_km"]
            session.primary_use = ser.validated_data["primary_use"]
            session.save(
                update_fields=["fuel_type_preference", "annual_km", "primary_use"]
            )

            
            emit_analytics_event.delay(
                str(session.id),
                "free_match_wizard_completed",
                {"has_current_vehicle": session.has_current_vehicle},
            )

        session.refresh_from_db()
        next_step = session.next_step

        if next_step is None:
            return Response({"match_ready": True})

        return Response({"next_step": next_step})



class FreeMatchCalculateView(views.APIView):
    """
    POST /api/free-match/{session_token}/match/

    Triggers the match calculation.  Returns a partial result with gated fields.
    """
    permission_classes = [AllowAny]
    throttle_scope = "anon"

    def post(self, request, session_token):
        session, err = _get_session_or_error(session_token)
        if err:
            return err

    
        if not session.step_1_complete:
            return Response(
                {"detail": "Step 1 (has_current_vehicle) must be answered before requesting a match."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if session.step_2_required and not session.step_2_complete:
            return Response(
                {"detail": "Step 2 (current vehicle details) must be answered before requesting a match."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not session.step_3_complete:
            return Response(
                {"detail": "Step 3 (fuel preference, annual km, primary use) must be answered before requesting a match."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            vehicle = match_vehicle_for_wizard(session)
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

        session.matched_vehicle = vehicle
        session.save(update_fields=["matched_vehicle"])

        response_data = build_match_response(vehicle, session)

        emit_analytics_event.delay(
            str(session.id),
            "free_match_result_viewed",
            {},
        )

        return Response(response_data, status=status.HTTP_200_OK)


class FreeMatchSaveView(views.APIView):
    """
    POST /api/free-match/{session_token}/save/

    Requires authentication (visitor has just registered).
    Saves the matched vehicle to the new user's MyGarage and unlocks
    all gated fields.

    This is the only persistent outcome of the wizard.  If the user
    instead calls DELETE (discard), nothing is stored.
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

        garage_vehicle = GarageVehicle.objects.create(
            user=user,
            vehicle_catalogue=session.matched_vehicle,
            source=GarageVehicleSource.FREE_MATCH_WIZARD,
        )

        session.converted_user = user
        session.save(update_fields=["converted_user"])

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
    No result is stored anywhere after this call.
    """
    permission_classes = [AllowAny]
    throttle_scope = "anon"

    def delete(self, request, session_token):
        try:
            session = FreeMatchSession.objects.get(session_token=session_token)
        except FreeMatchSession.DoesNotExist:
            return Response({"discarded": True}, status=status.HTTP_200_OK)

        emit_analytics_event.delay(
            str(session.id),
            "free_match_discarded",
            {},
        )

        session.delete()

        return Response({"discarded": True}, status=status.HTTP_200_OK)
