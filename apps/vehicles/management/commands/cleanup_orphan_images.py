import os
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.vehicles.models import Vehicle


class Command(BaseCommand):
    help = (
        "Delete image files under MEDIA_ROOT/vehicle_images that are not referenced "
        "by any Vehicle.image_url. Frees server disk. Use --dry-run to preview."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be deleted without deleting")
        parser.add_argument("--path", type=str, default="",
                            help="Directory to clean (default MEDIA_ROOT/vehicle_images)")

    def handle(self, *args, **options):
        media_root = getattr(settings, "MEDIA_ROOT", None)
        if not media_root:
            self.stderr.write(self.style.ERROR("MEDIA_ROOT is not set; refusing to run."))
            return

        target = options["path"] or os.path.join(str(media_root), "vehicle_images")
        target = os.path.realpath(target)
        media_root_real = os.path.realpath(str(media_root))

        if not (target == media_root_real or target.startswith(media_root_real + os.sep)):
            self.stderr.write(
                self.style.ERROR(f"Refusing to run: {target} is outside MEDIA_ROOT ({media_root_real})")
            )
            return
        if not os.path.isdir(target):
            self.stderr.write(f"Nothing to do: {target} does not exist.")
            return

        referenced = set()
        for url in Vehicle.objects.exclude(image_url__isnull=True).exclude(image_url="").values_list(
            "image_url", flat=True
        ):
            referenced.add(os.path.basename(urlparse(url).path or url))

        orphan_count = 0
        orphan_bytes = 0
        for name in sorted(os.listdir(target)):
            file_path = os.path.join(target, name)
            if not os.path.isfile(file_path):
                continue
            if name in referenced:
                continue
            size = os.path.getsize(file_path)
            orphan_count += 1
            orphan_bytes += size
            if options["dry_run"]:
                self.stdout.write(f"would delete {name} ({size} bytes)")
            else:
                try:
                    os.remove(file_path)
                except OSError as e:
                    self.stderr.write(f"WARN could not delete {file_path}: {e}")
                    orphan_count -= 1
                    orphan_bytes -= size

        verb = "Would delete" if options["dry_run"] else "Deleted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {orphan_count} orphan file(s), "
                f"{orphan_bytes} bytes ({orphan_bytes / (1024 * 1024):.1f} MiB)."
            )
        )
