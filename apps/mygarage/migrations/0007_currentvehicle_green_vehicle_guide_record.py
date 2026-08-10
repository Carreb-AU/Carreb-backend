# Generated manually for GVG Option A integration

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mygarage', '0006_garagevehicle_re_subscribe_required_and_more'),
        ('vehicles', '0006_datasource_categorycostdefault_greenvehicleguiderecord'),
    ]

    operations = [
        migrations.AddField(
            model_name='currentvehicle',
            name='green_vehicle_guide_record',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='current_vehicles', to='vehicles.greenvehicleguiderecord'),
        ),
    ]
