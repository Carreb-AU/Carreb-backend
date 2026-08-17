from django.core.management.base import BaseCommand
from apps.vehicles.models import Vehicle, VehicleIdentity


class Command(BaseCommand):
    help = 'Set a fallback image_url for vehicles or VehicleIdentity records that currently have none.'

    def add_arguments(self, parser):
        parser.add_argument('url', type=str, help='Fallback image URL to apply')
        parser.add_argument(
            '--vehicle-identity',
            action='store_true',
            help='Apply fallback to VehicleIdentity records instead of Vehicle',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print how many records would be updated without changing them',
        )

    def handle(self, *args, **options):
        url = options['url']
        dry_run = options['dry_run']
        use_identity = options['vehicle_identity']

        model = VehicleIdentity if use_identity else Vehicle
        label = 'VehicleIdentity records' if use_identity else 'vehicles'

        qs = model.objects.filter(image_url__isnull=True) | model.objects.filter(image_url='')
        count = qs.count()

        if dry_run:
            self.stdout.write(f'Would update {count} {label} with fallback URL: {url}')
            return

        updated = qs.update(image_url=url)
        self.stdout.write(
            self.style.SUCCESS(f'Updated {updated} {label} with fallback image_url: {url}')
        )
