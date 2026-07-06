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


class PriorityPreference(models.TextChoices):
    COST_ONLY = "cost_only", "Cost Only"
    MOSTLY_COST = "mostly_cost", "Mostly Cost"
    BALANCED = "balanced", "Balanced"
    MOSTLY_GREEN = "mostly_green", "Mostly Green"
    GREEN_ONLY = "green_only", "Green Only"


class FreeMatchSession(models.Model):
    """
    Represents one anonymous wizard run using the single API flow.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    session_token = models.CharField(
        max_length=64,
        unique=True,
        default=_generate_session_token,
        db_index=True,
    )

    priority = models.CharField(
        max_length=20,
        choices=PriorityPreference.choices,
        default=PriorityPreference.BALANCED,
    )
    primary_use = models.CharField(
        max_length=20,
        choices=PrimaryUse.choices,
        null=True,
        blank=True,
    )
    annual_km = models.IntegerField(null=True, blank=True)
    budget_min = models.IntegerField(null=True, blank=True)
    budget_max = models.IntegerField(null=True, blank=True)
    state = models.CharField(max_length=10, null=True, blank=True)

    has_current_vehicle = models.BooleanField(default=False)
    current_vehicle_make = models.CharField(max_length=100, null=True, blank=True)
    current_vehicle_model = models.CharField(max_length=100, null=True, blank=True)
    current_vehicle_year = models.IntegerField(null=True, blank=True)
    current_vehicle_odometer = models.IntegerField(null=True, blank=True)

    fuel_type_preference = models.CharField(
        max_length=20,
        choices=FuelTypePreference.choices,
        null=True,
        blank=True,
    )
    style_preference = models.CharField(max_length=100, null=True, blank=True)
    seating_preference = models.IntegerField(null=True, blank=True)
    ancap_5_star_only = models.BooleanField(default=False)
    towing_capacity_required = models.BooleanField(default=False)

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
