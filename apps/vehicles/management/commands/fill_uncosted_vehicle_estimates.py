"""
Fill default-based cost/CO2/scoring estimates for Carreb catalogue vehicles
that arrived from the workbook without cost data (mode_coo_pa missing in every
state/mode of mode_data_by_state).

Usage:
    python manage.py fill_uncosted_vehicle_estimates              # dry run
    python manage.py fill_uncosted_vehicle_estimates --commit
    python manage.py fill_uncosted_vehicle_estimates --vehicle-id <uuid> --commit
    python manage.py fill_uncosted_vehicle_estimates --limit 5 --commit
"""

from django.core.management.base import BaseCommand

from apps.vehicles.services.uncosted_estimates import (
    _Lookups,
    apply_estimates,
    compute_vehicle_estimates,
    find_uncosted_vehicles,
)


class Command(BaseCommand):
    help = "Fill sheet-default cost estimates for uncosted catalogue vehicles."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Write changes (default is a dry run).")
        parser.add_argument("--limit", type=int, default=None, help="Process at most N vehicles.")
        parser.add_argument("--vehicle-id", type=str, default=None, help="Process one vehicle by UUID.")

    def handle(self, *args, **options):
        commit = options["commit"]
        lookups = _Lookups()

        if options["vehicle_id"]:
            from apps.vehicles.models import Vehicle
            qs = Vehicle.objects.filter(pk=options["vehicle_id"])
            if not qs.exists():
                self.stderr.write(f"No vehicle with id {options['vehicle_id']}")
                return
        else:
            qs = find_uncosted_vehicles()
        if options["limit"]:
            qs = qs[: options["limit"]]

        total = qs.count()
        self.stdout.write(f"{'COMMIT' if commit else 'DRY RUN'}: {total} vehicle(s) to process")

        done = skipped = failed = 0
        for vehicle in qs.iterator():
            try:
                result = compute_vehicle_estimates(vehicle, lookups)
                if not result:
                    self.stdout.write(f"SKIP {vehicle.brand} {vehicle.model} {vehicle.year}: no cost category or driveaway")
                    skipped += 1
                    continue
                summary = apply_estimates(vehicle, result, commit=commit)
                done += 1
                mode = summary["mode_coo_nsw"] or {}
                self.stdout.write(
                    f"{'WROTE' if commit else 'OK   '} {vehicle.brand} {vehicle.model} {vehicle.year} "
                    f"[{summary['cost_category']}] base={summary['base_coo_nsw']} "
                    f"B={mode.get('B')} C={mode.get('C')} E={mode.get('E')} F={mode.get('F')} "
                    f"stars(B)={summary['stars']['B']} co2={summary['energy_cycle_national']} "
                    f"{'; '.join(summary['estimated_fields'])}"
                )
            except Exception as exc:  # noqa: BLE001 - report and continue the batch
                failed += 1
                self.stderr.write(f"FAIL {vehicle.brand} {vehicle.model} {vehicle.year}: {exc}")

        self.stdout.write(f"Done: {done} filled, {skipped} skipped, {failed} failed.")
