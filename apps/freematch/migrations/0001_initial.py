import django.db.models.deletion
import django.utils.timezone
import apps.freematch.models
from django.conf import settings
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("vehicles", "0002_vehicle_total_5yr_cost_of_ownership_by_state_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FreeMatchSession",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "session_token",
                    models.CharField(
                        default=apps.freematch.models._generate_session_token,
                        db_index=True,
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "has_current_vehicle",
                    models.BooleanField(blank=True, null=True),
                ),
                (
                    "current_vehicle_make",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                (
                    "current_vehicle_model",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                (
                    "current_vehicle_year",
                    models.IntegerField(blank=True, null=True),
                ),
                (
                    "fuel_type_preference",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("petrol", "Petrol"),
                            ("diesel", "Diesel"),
                            ("mild_hybrid", "Mild Hybrid"),
                            ("hybrid", "Hybrid"),
                            ("phev", "Plug-in Hybrid (PHEV)"),
                            ("bev", "Battery Electric (BEV)"),
                            ("fcev", "Hydrogen / FCEV"),
                            ("no_preference", "No Preference"),
                        ],
                        max_length=20,
                        null=True,
                    ),
                ),
                (
                    "annual_km",
                    models.IntegerField(blank=True, null=True),
                ),
                (
                    "primary_use",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("city_commuter", "City Commuter"),
                            ("family_car", "Family Car"),
                            ("mixed_use", "Mixed Use"),
                            ("long_distance", "Long Distance"),
                            ("work_vehicle", "Work Vehicle"),
                        ],
                        max_length=20,
                        null=True,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "expires_at",
                    models.DateTimeField(
                        default=apps.freematch.models._default_expires_at
                    ),
                ),
                (
                    "converted_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="free_match_conversions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "matched_vehicle",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="free_match_sessions",
                        to="vehicles.vehicle",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="freematchsession",
            index=models.Index(
                fields=["session_token"], name="freematch_f_session_56dbb5_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="freematchsession",
            index=models.Index(
                fields=["expires_at"], name="freematch_f_expires_481958_idx"
            ),
        ),
    ]
