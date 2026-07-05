import uuid
import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone


def _default_expires_at():
    """Sessions expire 2 hours after creation — for cleanup only."""
    return timezone.now() + timedelta(hours=2)


def _generate_session_token():
    """Cryptographically secure URL-safe token."""
    return secrets.token_urlsafe(32)


class FuelTypePreference(models.TextChoices):
    PETROL = "petrol", "Petrol"
    DIESEL = "diesel", "Diesel"
    MILD_HYBRID = "mild_hybrid", "Mild Hybrid"
    HYBRID = "hybrid", "Hybrid"
    PHEV = "phev", "Plug-in Hybrid (PHEV)"
    BEV = "bev", "Battery Electric (BEV)"
    FCEV = "fcev", "Hydrogen / FCEV"
    NO_PREFERENCE = "no_preference", "No Preference"


class PrimaryUse(models.TextChoices):
    CITY_COMMUTER = "city_commuter", "City Commuter"
    FAMILY_CAR = "family_car", "Family Car"
    MIXED_USE = "mixed_use", "Mixed Use"
    LONG_DISTANCE = "long_distance", "Long Distance"
    WORK_VEHICLE = "work_vehicle", "Work Vehicle"


class FreeMatchSession(models.Model):
    """
    Represents one anonymous wizard run.

    session_token is a short-lived opaque token used only within the
    multi-step wizard flow.  It is NOT a login session and must never
    be used for result retrieval once the wizard ends.

    expires_at is stored purely for the nightly cleanup job — it does
    not gate result retrieval (results are discarded on DELETE, or
    unlocked immediately on POST /save/).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    session_token = models.CharField(
        max_length=64,
        unique=True,
        default=_generate_session_token,
        db_index=True,
    )

    
    has_current_vehicle = models.BooleanField(null=True, blank=True)

    
    current_vehicle_make = models.CharField(max_length=100, null=True, blank=True)
    current_vehicle_model = models.CharField(max_length=100, null=True, blank=True)
    current_vehicle_year = models.IntegerField(null=True, blank=True)

    
    fuel_type_preference = models.CharField(
        max_length=20,
        choices=FuelTypePreference.choices,
        null=True,
        blank=True,
    )
    annual_km = models.IntegerField(null=True, blank=True)
    primary_use = models.CharField(
        max_length=20,
        choices=PrimaryUse.choices,
        null=True,
        blank=True,
    )

    
    matched_vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="free_match_sessions",
    )

   
    converted_user = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="free_match_conversions",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expires_at)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session_token"], name="freematch_f_session_56dbb5_idx"),
            models.Index(fields=["expires_at"], name="freematch_f_expires_481958_idx"),
        ]

    def __str__(self):
        return f"FreeMatchSession {self.session_token[:8]}… (exp {self.expires_at.isoformat()})"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def step_1_complete(self):
        return self.has_current_vehicle is not None

    @property
    def step_2_required(self):
        return self.has_current_vehicle is True

    @property
    def step_2_complete(self):
        if not self.step_2_required:
            return True  
        return all([
            self.current_vehicle_make,
            self.current_vehicle_model,
            self.current_vehicle_year,
        ])

    @property
    def step_3_complete(self):
        return all([
            self.fuel_type_preference is not None,
            self.annual_km is not None,
            self.primary_use is not None,
        ])

    @property
    def all_steps_complete(self):
        return self.step_1_complete and self.step_2_complete and self.step_3_complete

    @property
    def next_step(self):
        """
        Returns the integer number of the next step to be answered,
        or None if all steps are complete.
        """
        if not self.step_1_complete:
            return 1
        if self.step_2_required and not self.step_2_complete:
            return 2
        if not self.step_3_complete:
            return 3
        return None
