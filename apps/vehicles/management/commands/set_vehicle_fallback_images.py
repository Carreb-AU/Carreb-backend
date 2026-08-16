from django.core.management.base import BaseCommand
from apps.vehicles.models import Vehicle


class Command(BaseCommand):
    help = 'Set a fallback image_url for all vehicles that currently have none.'

    def add_arguments(self, parser):
        parser.add_argument('url', type=str, help='Fallback image URL to apply')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print how many vehicles would be updated without changing them',
        )

    def handle(self, *args, **options):
        url = options['url']
        dry_run = options['dry_run']

        qs = Vehicle.objects.filter(image_url__isnull=True) | Vehicle.objects.filter(image_url='')
        count = qs.count()

        if dry_run:
            self.stdout.write(f'Would update {count} vehicles with fallback URL: {url}')
            return

        updated = qs.update(image_url=url)
        self.stdout.write(
            self.style.SUCCESS(f'Updated {updated} vehicles with fallback image_url: {url}')
        )
