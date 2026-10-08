from django.core.management.base import BaseCommand
from django.db import transaction
from apps.mygarage.models import CurrentVehicle
from apps.vehicles.models import VehicleIdentity


class Command(BaseCommand):
    help = (
        'Remove duplicate VehicleIdentity rows created by repeated GVG imports.\n\n'
        'For each natural key (source_dataset, make, model, year, variant) the oldest '
        'row (by imported_at, then id) is kept; the rest are deleted after re-pointing '
        'any CurrentVehicle FKs at the kept row. Idempotent and safe to re-run.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report how many duplicates would be removed without deleting anything',
        )
        parser.add_argument(
            '--batch',
            type=int,
            default=5000,
            help='Number of duplicate rows to delete per query (default: 5000)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        batch_size = options['batch']

        rows = VehicleIdentity.objects.values_list(
            'id', 'source_dataset', 'make', 'model', 'year', 'variant', 'imported_at'
        )

        # Group row ids by natural key, preserving import order (oldest first).
        groups = {}
        for pk, dataset, make, model, year, variant, imported_at in rows.iterator():
            key = (dataset, make, model, year, variant)
            groups.setdefault(key, []).append((imported_at, pk))

        keep_ids, dupe_ids, fk_repointers = [], [], {}
        for key, members in groups.items():
            members.sort()  # oldest imported_at first; id breaks ties
            keeper = members[0][1]
            keep_ids.append(keeper)
            for _, pk in members[1:]:
                dupe_ids.append(pk)
                fk_repointers[pk] = keeper

        total = len(keep_ids) + len(dupe_ids)
        self.stdout.write(
            f'VehicleIdentity rows: {total} total, {len(keep_ids)} unique keys, '
            f'{len(dupe_ids)} duplicates to remove.'
        )

        if dry_run:
            return

        fk_moves = 0
        with transaction.atomic():
            # Re-point users' current vehicles BEFORE deleting, inside one
            # transaction. Only dupes actually referenced by a CurrentVehicle
            # need an UPDATE — normally none or a handful.
            referenced = set(
                CurrentVehicle.objects.filter(
                    green_vehicle_guide_record_id__in=dupe_ids
                ).values_list('green_vehicle_guide_record_id', flat=True).distinct()
            )
            for dupe_id in referenced:
                fk_moves += CurrentVehicle.objects.filter(
                    green_vehicle_guide_record_id=dupe_id
                ).update(green_vehicle_guide_record_id=fk_repointers[dupe_id])

            for i in range(0, len(dupe_ids), batch_size):
                VehicleIdentity.objects.filter(
                    id__in=dupe_ids[i:i + batch_size]
                ).delete()

        self.stdout.write(self.style.SUCCESS(
            f'Deleted {len(dupe_ids)} duplicates; re-pointed {fk_moves} current vehicle(s). '
            f'{len(keep_ids)} rows remain.'
        ))
