# Generated 14-Oct-26 — adds 13-Oct-26 workbook fields to Vehicle.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0030_vehicle_consolidated_v64_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicle',
            name='co2_energy_cycle_g_per_km',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='vehicle',
            name='spotlight_data',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
