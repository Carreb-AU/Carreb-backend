# Generated manually: add ManualVehicleEnrichment model

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0008_greenvehicleguiderecord_provenance'),
    ]

    operations = [
        migrations.CreateModel(
            name='ManualVehicleEnrichment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('engine_l', models.FloatField(blank=True, null=True)),
                ('ancap_safety_rating', models.IntegerField(blank=True, null=True)),
                ('image_url', models.URLField(blank=True, max_length=2000, null=True)),
                ('driveaway_price_estimate', models.IntegerField(blank=True, null=True)),
                ('resale_value_5yr_estimate', models.IntegerField(blank=True, null=True)),
                ('notes', models.TextField(blank=True, default='')),
                ('enriched_by', models.CharField(blank=True, max_length=255)),
                ('enriched_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('record', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='manual_enrichment', to='vehicles.greenvehicleguiderecord')),
            ],
            options={
                'verbose_name': 'Manual Vehicle Enrichment',
                'verbose_name_plural': 'Manual Vehicle Enrichments',
            },
        ),
    ]
