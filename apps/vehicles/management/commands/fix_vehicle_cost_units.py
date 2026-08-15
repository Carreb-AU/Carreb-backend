"""
One-time fix for vehicles whose monetary fields were stored as dollars by the
legacy Carreb ETL. Converts them to whole cents in place.

Safe to re-run: after values are already cents, the command will not change them.
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from apps.vehicles.models import Vehicle


def _to_cents(value):
    """Convert a dollar value to whole cents. Returns None if value is not numeric."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        return int(round(value * 100))
    if isinstance(value, int):
        return value
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def _convert_json_field(state_dict: dict) -> tuple[dict, bool]:
    """Convert any float dollar values in a state-level JSON dict to cents."""
    if not state_dict:
        return state_dict, False

    changed = False
    new_dict = {}
    for state, value in state_dict.items():
        if isinstance(value, float):
            new_dict[state] = _to_cents(value)
            changed = True
        else:
            new_dict[state] = value
    return new_dict, changed


class Command(BaseCommand):
    help = "Convert legacy dollar-stored vehicle cost fields to cents in place."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        json_fields = [
            "driveaway_price_by_state",
            "insurance_estimate_by_state",
            "ctp_by_state",
            "registration_by_state",
            "fuel_cost_by_state",
            "electricity_cost_by_state",
            "ev_levy_by_state",
            "base_coo_by_state",
            "components_sum_by_state",
            "total_5yr_cost_of_ownership_by_state",
        ]

        int_fields = [
            "servicing_5yr_estimate",
            "tyre_replacement_estimate",
            "resale_value_5yr_estimate",
        ]

        changed_count = 0
        checked_count = 0
        to_update = []

        qs = Vehicle.objects.all().only(
            "id",
            *json_fields,
            *int_fields,
        )

        for vehicle in qs.iterator(chunk_size=500):
            checked_count += 1
            vehicle_changed = False

            for field_name in json_fields:
                old = getattr(vehicle, field_name) or {}
                new, field_changed = _convert_json_field(old)
                if field_changed:
                    setattr(vehicle, field_name, new)
                    vehicle_changed = True

            for field_name in int_fields:
                value = getattr(vehicle, field_name)
                if value is None:
                    continue
                # The legacy ETL stored these as int dollars. If the value is a
                # small-ish int, treat it as dollars and convert to cents.
                if isinstance(value, (int, float)) and 0 < value < 1_000_000:
                    setattr(vehicle, field_name, _to_cents(value))
                    vehicle_changed = True

            if vehicle_changed:
                changed_count += 1
                to_update.append(vehicle)

            if len(to_update) >= 500:
                if not dry_run:
                    Vehicle.objects.bulk_update(to_update, fields=json_fields + int_fields)
                to_update = []

        if to_update and not dry_run:
            Vehicle.objects.bulk_update(to_update, fields=json_fields + int_fields)

        action = "Would update" if dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {changed_count} of {checked_count} Vehicle records."
            )
        )
