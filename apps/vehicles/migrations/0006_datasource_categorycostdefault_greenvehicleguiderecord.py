# Generated manually for GVG Option A integration

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0005_alter_vehicle_image_url'),
    ]

    operations = [
        migrations.CreateModel(
            name='DataSource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=50, unique=True)),
                ('name', models.CharField(max_length=255)),
                ('url', models.URLField(blank=True)),
                ('dataset_type', models.CharField(blank=True, max_length=50)),
                ('retrieved_at', models.DateTimeField(blank=True, null=True)),
                ('archived_file', models.FileField(blank=True, null=True, upload_to='data/source_archives/')),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['code'],
            },
        ),
        migrations.CreateModel(
            name='CategoryCostDefault',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('fcai_category', models.CharField(max_length=100)),
                ('fcai_broad', models.CharField(blank=True, max_length=100)),
                ('state', models.CharField(max_length=10)),
                ('annual_km', models.IntegerField(default=13300)),
                ('ctp_pa', models.IntegerField(blank=True, null=True)),
                ('comprehensive_pa', models.IntegerField(blank=True, null=True)),
                ('registration_pa', models.IntegerField(blank=True, null=True)),
                ('maintenance_pa', models.IntegerField(blank=True, null=True)),
                ('tyre_cost_pa', models.IntegerField(blank=True, null=True)),
                ('fuel_cost_pa', models.IntegerField(blank=True, null=True)),
                ('electricity_cost_pa', models.IntegerField(blank=True, null=True)),
                ('ev_levy_pa', models.IntegerField(blank=True, null=True)),
                ('components_sum_pa', models.IntegerField(blank=True, null=True)),
                ('servicing_5yr_estimate', models.IntegerField(blank=True, null=True)),
                ('tyre_replacement_estimate', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['fcai_category', 'state'],
                'unique_together': {('fcai_category', 'state')},
            },
        ),
        migrations.CreateModel(
            name='GreenVehicleGuideRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('make', models.CharField(max_length=100)),
                ('model', models.CharField(max_length=100)),
                ('year', models.IntegerField()),
                ('variant', models.CharField(blank=True, max_length=255)),
                ('body_style', models.CharField(blank=True, max_length=100)),
                ('fcai_category', models.CharField(blank=True, max_length=100)),
                ('fcai_broad', models.CharField(blank=True, max_length=100)),
                ('powertrain_type', models.CharField(blank=True, choices=[('petrol', 'Petrol'), ('diesel', 'Diesel'), ('mild_hybrid', 'Mild Hybrid'), ('hybrid', 'Hybrid'), ('phev', 'Plug-in Hybrid (PHEV)'), ('bev', 'Battery Electric (BEV)'), ('fcev', 'Hydrogen / FCEV')], max_length=50)),
                ('fuel_type_raw', models.CharField(blank=True, max_length=100)),
                ('engine_l', models.FloatField(blank=True, null=True)),
                ('battery_kwh', models.FloatField(blank=True, null=True)),
                ('num_seats', models.IntegerField(blank=True, null=True)),
                ('transmission', models.CharField(blank=True, max_length=100)),
                ('fuel_consumption_combined_l_100km', models.FloatField(blank=True, null=True)),
                ('fuel_consumption_urban_l_100km', models.FloatField(blank=True, null=True)),
                ('fuel_consumption_extra_urban_l_100km', models.FloatField(blank=True, null=True)),
                ('electricity_consumption_wh_per_km', models.FloatField(blank=True, null=True)),
                ('electric_range_km', models.FloatField(blank=True, null=True)),
                ('tailpipe_co2_g_per_km', models.FloatField(blank=True, null=True)),
                ('annual_fuel_cost', models.IntegerField(blank=True, null=True)),
                ('driveaway_price_estimate', models.IntegerField(blank=True, null=True)),
                ('insurance_estimate_by_state', models.JSONField(blank=True, default=dict)),
                ('ctp_by_state', models.JSONField(blank=True, default=dict)),
                ('registration_by_state', models.JSONField(blank=True, default=dict)),
                ('servicing_5yr_estimate', models.IntegerField(blank=True, null=True)),
                ('tyre_replacement_estimate', models.IntegerField(blank=True, null=True)),
                ('resale_value_5yr_estimate', models.IntegerField(blank=True, null=True)),
                ('total_5yr_cost_of_ownership_by_state', models.JSONField(blank=True, default=dict)),
                ('is_current_model', models.BooleanField(blank=True, null=True)),
                ('model_end_year', models.IntegerField(blank=True, null=True)),
                ('test_cycle', models.CharField(blank=True, max_length=50)),
                ('source_dataset', models.CharField(blank=True, max_length=50)),
                ('raw_data', models.JSONField(blank=True, default=dict)),
                ('imported_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('source', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='vehicles.datasource')),
            ],
            options={
                'ordering': ['make', 'model', 'year', 'variant'],
            },
        ),
        migrations.AddIndex(
            model_name='greenvehicleguiderecord',
            index=models.Index(fields=['make', 'model', 'year'], name='vehicles_gr_make_mod_yea_9c3d53_idx'),
        ),
        migrations.AddIndex(
            model_name='greenvehicleguiderecord',
            index=models.Index(fields=['powertrain_type'], name='vehicles_gr_powertr_5c3d53_idx'),
        ),
        migrations.AddIndex(
            model_name='greenvehicleguiderecord',
            index=models.Index(fields=['fcai_category'], name='vehicles_gr_fcai_ca_7a3d53_idx'),
        ),
    ]
