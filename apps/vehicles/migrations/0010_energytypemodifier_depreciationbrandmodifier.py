# Generated manually: add EnergyTypeModifier and DepreciationBrandModifier models

from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0009_manualvehicleenrichment'),
    ]

    operations = [
        migrations.CreateModel(
            name='EnergyTypeModifier',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('powertrain_type', models.CharField(
                    choices=[
                        ('petrol', 'Petrol'),
                        ('diesel', 'Diesel'),
                        ('mild_hybrid', 'Mild Hybrid'),
                        ('hybrid', 'Hybrid'),
                        ('phev', 'Plug-in Hybrid (PHEV)'),
                        ('bev', 'Battery Electric (BEV)'),
                        ('fcev', 'Hydrogen / FCEV'),
                    ],
                    max_length=50,
                    unique=True,
                )),
                ('fuel_cost_multiplier', models.FloatField(default=1.0)),
                ('electricity_cost_multiplier', models.FloatField(default=1.0)),
                ('servicing_cost_multiplier', models.FloatField(default=1.0)),
                ('tyre_cost_multiplier', models.FloatField(default=1.0)),
                ('insurance_cost_multiplier', models.FloatField(default=1.0)),
                ('registration_cost_multiplier', models.FloatField(default=1.0)),
                ('resale_value_multiplier', models.FloatField(default=1.0)),
                ('retention_multiplier', models.FloatField(default=1.0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Energy Type Modifier',
                'verbose_name_plural': 'Energy Type Modifiers',
            },
        ),
        migrations.CreateModel(
            name='DepreciationBrandModifier',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('brand', models.CharField(max_length=255, unique=True)),
                ('retention_multiplier', models.FloatField(default=1.0)),
                ('resale_value_multiplier', models.FloatField(default=1.0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Depreciation Brand Modifier',
                'verbose_name_plural': 'Depreciation Brand Modifiers',
            },
        ),
    ]
