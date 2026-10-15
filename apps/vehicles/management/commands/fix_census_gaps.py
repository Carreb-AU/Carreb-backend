"""One-off census gap-filler.

Fills the two remaining census gaps:

1. BEVs with no electricity_consumption_per_100km get the client's flat
   180 Wh/km convention (Forensic #28, flagged in every BEV row's data_flags)
   = 18.0 kWh/100km — the same rate the sheet's electricity costs are computed
   on. Marked as an estimate in fe_basis / data_flags.
2. Vehicles with no image_url get an FCAI silhouette URL matched on their
   fcai_category / body_style / drive (the same fallback the API uses at
   request time).

Idempotent: safe to re-run; it only touches rows that are still empty.
"""
from django.core.management.base import BaseCommand

from apps.vehicles.models import Vehicle, PowertrainType
from apps.vehicles.services.silhouette_lookup import get_silhouette_url

BEV_FLAT_KWH_PER_100KM = 18.0  # 180 Wh/km, client convention (Forensic #28)
ESTIMATE_NOTE = (
    "ESTIMATED: flat 180 Wh/km client convention (Forensic #28) - "
    "battery TBC in source sheet"
)


class Command(BaseCommand):
    help = "Fill census gaps: estimated BEV consumption + silhouette image fallbacks."

    def handle(self, *args, **options):
        bevs = Vehicle.objects.filter(
            powertrain_type=PowertrainType.BEV,
            electricity_consumption_per_100km__isnull=True,
        )
        n = bevs.update(
            electricity_consumption_per_100km=BEV_FLAT_KWH_PER_100KM,
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
