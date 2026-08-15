import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.vehicles.models import Vehicle, PowertrainType
from apps.config.models import SiteConfig


class Command(BaseCommand):
    help = (
        'Run the market-completeness census against the Carreb vehicle catalogue. '
        'Emits substantiation_YYYYMMDD.json and asserts missing_count == 0. '
        'Updates the SiteConfig homepage vehicle-count claim.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            type=str,
            default=os.path.join(settings.BASE_DIR, 'docs', 'substantiation'),
            help='Directory where substantiation_YYYYMMDD.json is written.',
        )
        parser.add_argument(
            '--claim-template',
            type=str,
            default='{count:,}+',
            help='Python format template for the public count claim.',
        )
        parser.add_argument(
            '--no-update-config',
            action='store_true',
            help='Do not update SiteConfig.homepage_vehicle_count_claim.',
        )

    def handle(self, *args, **options):
        output_dir = options['output_dir']
        claim_template = options['claim_template']
        no_update_config = options['no_update_config']

        os.makedirs(output_dir, exist_ok=True)

        required_fields = {
            'brand': 'identity',
            'model': 'identity',
            'year': 'identity',
            'variant': 'identity',
            'body_style': 'identity',
            'powertrain_type': 'identity',
            'fcai_category': 'classification',
            'test_cycle': 'emissions',
            'image_url': 'media',
        }

        # Consumption: fuel or electricity must be present, depending on powertrain.
        def has_consumption(v: Vehicle) -> bool:
            if v.powertrain_type == PowertrainType.BEV:
                return v.electricity_consumption_per_100km is not None
            return v.fuel_consumption_per_100km is not None

        def has_driveaway(v: Vehicle) -> bool:
            return bool(v.driveaway_price_by_state and any(v.driveaway_price_by_state.values()))

        def has_mode_data(v: Vehicle) -> bool:
            return bool(v.mode_data_by_state and any(v.mode_data_by_state.values()))

        total_count = 0
        missing_count = 0
        missing_vehicles: List[Dict[str, Any]] = []

        for v in Vehicle.objects.all().order_by('brand', 'model', 'year', 'variant'):
            total_count += 1
            missing_fields = []

            for field, category in required_fields.items():
                value = getattr(v, field, None)
                if value is None or value == '':
                    missing_fields.append({'field': field, 'category': category})

            if v.tailpipe_co2_g_per_km is None:
                missing_fields.append({'field': 'tailpipe_co2_g_per_km', 'category': 'emissions'})

            if not has_consumption(v):
                missing_fields.append({'field': 'fuel_or_electricity_consumption', 'category': 'consumption'})

            if not has_driveaway(v):
                missing_fields.append({'field': 'driveaway_price_by_state', 'category': 'pricing'})

            if not has_mode_data(v):
                missing_fields.append({'field': 'mode_data_by_state', 'category': 'scoring'})

            if missing_fields:
                missing_count += 1
                missing_vehicles.append({
                    'id': str(v.id),
                    'name': str(v),
                    'missing_fields': missing_fields,
                })

        run_date = datetime.now(timezone.utc)
        run_date_str = run_date.strftime('%Y%m%d')

        substantiation = {
            'schema_version': '1.0',
            'run_date': run_date.isoformat(),
            'vehicle_count': {
                'total': total_count,
                'missing': missing_count,
                'complete': total_count - missing_count,
            },
            'criteria': {
                'required_identity_fields': list(required_fields.keys()),
                'required_emissions_fields': ['tailpipe_co2_g_per_km', 'test_cycle'],
                'required_consumption_fields': ['fuel_consumption_per_100km or electricity_consumption_per_100km'],
                'required_pricing_fields': ['driveaway_price_by_state (at least one state)'],
                'required_scoring_fields': ['mode_data_by_state (at least one state/mode)'],
            },
            'missing_vehicles': missing_vehicles,
            'claim': claim_template.format(count=total_count),
            'missing_count': missing_count,
        }

        output_path = os.path.join(output_dir, f'substantiation_{run_date_str}.json')
        with open(output_path, 'w') as f:
            json.dump(substantiation, f, indent=2)

        if not no_update_config:
            config = SiteConfig.get()
            config.homepage_vehicle_count_claim = claim_template.format(count=total_count)
            config.save()

        self.stdout.write(self.style.SUCCESS(f'Census complete. Total: {total_count}, Missing: {missing_count}'))
        self.stdout.write(self.style.SUCCESS(f'Wrote {output_path}'))

        if missing_count > 0:
            raise CommandError(
                f'Census failed: missing_count={missing_count}. '
                f'See {output_path} for details.'
            )
