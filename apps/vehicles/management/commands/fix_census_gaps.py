"""One-off census gap-filler.

Fills the two remaining census gaps that no source sheet provides:

1. BEVs whose source sheet battery size is "Not in source" (unreleased/TBC
   models) get electricity_consumption_per_100km set to the fleet average of
   BEVs that do have data (16.1 kWh/100km at import time), clearly marked as
   an estimate in fe_basis / data_flags.
2. Vehicles with no image_url get an FCAI silhouette URL matched on their
   fcai_category / body_style / drive (the same fallback the API uses at
   request time).

Idempotent: safe to re-run; it only touches rows that are still empty.
"""
from django.core.management.base import BaseCommand

from apps.vehicles.models import Vehicle, PowertrainType
from apps.vehicles.services.silhouette_lookup import get_silhouette_url

FLEET_AVG_BEV_KWH_PER_100KM = 16.1
ESTIMATE_NOTE = (
    "ESTIMATED: fleet average 16.1 kWh/100km - battery TBC in source sheet"
)


class Command(BaseCommand):
    help = "Fill census gaps: estimated BEV consumption + silhouette image fallbacks."

    def handle(self, *args, **options):
        bevs = Vehicle.objects.filter(
            powertrain_type=PowertrainType.BEV,
            electricity_consumption_per_100km__isnull=True,
        )
        n = bevs.update(
            electricity_consumption_per_100km=FLEET_AVG_BEV_KWH_PER_100KM,
            fe_basis=ESTIMATE_NOTE,
            data_flags="consumption_estimated",
        )
        self.stdout.write(self.style.SUCCESS(f"Filled {n} BEVs with estimated consumption"))

        no_image = list(Vehicle.objects.filter(image_url__isnull=True)) + list(
            Vehicle.objects.filter(image_url="")
        )
        fixed = 0
        for v in no_image:
            url = get_silhouette_url(v.fcai_category, v.body_style, v.drive)
            Vehicle.objects.filter(id=v.id).update(image_url=url)
            fixed += 1
        self.stdout.write(self.style.SUCCESS(f"Set silhouette fallback on {fixed} vehicles"))
