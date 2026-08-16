from django.core.management.base import BaseCommand

from apps.vehicles.models import (
    PowertrainType,
    Vehicle,
    VehicleIdentity,
    EnergyTypeModifier,
    DepreciationBrandModifier,
)


class Command(BaseCommand):
    help = (
        "Seed default 1.0 modifier rows for EnergyTypeModifier and "
        "DepreciationBrandModifier. Existing rows are left untouched."
    )

    def handle(self, *args, **options):
        energy_created = 0
        for pt, _ in PowertrainType.choices:
            _, created = EnergyTypeModifier.objects.get_or_create(
                powertrain_type=pt,
                defaults={
                    'fuel_cost_multiplier': 1.0,
                    'electricity_cost_multiplier': 1.0,
                    'servicing_cost_multiplier': 1.0,
                    'tyre_cost_multiplier': 1.0,
                    'insurance_cost_multiplier': 1.0,
                    'registration_cost_multiplier': 1.0,
                    'resale_value_multiplier': 1.0,
                    'retention_multiplier': 1.0,
                },
            )
            if created:
                energy_created += 1

        brands = set()
        brands.update(
            Vehicle.objects.values_list('brand', flat=True).distinct()
        )
        brands.update(
            VehicleIdentity.objects.values_list('make', flat=True).distinct()
        )

        brand_created = 0
        for brand in brands:
            if not brand:
                continue
            _, created = DepreciationBrandModifier.objects.get_or_create(
                brand__iexact=brand,
                defaults={
                    'brand': brand,
                    'retention_multiplier': 1.0,
                    'resale_value_multiplier': 1.0,
                },
            )
            if created:
                brand_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {energy_created} energy-type modifiers and {brand_created} brand modifiers."
            )
        )
