# Generated manually: add provenance JSONField to GreenVehicleGuideRecord

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0007_greenvehicleguiderecord_search_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='greenvehicleguiderecord',
            name='provenance',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
