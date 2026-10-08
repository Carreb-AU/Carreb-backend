# Hand-written: adds Consolidated Vehicles v6.4 sheet fields to Vehicle

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0029_driveaway_tax_parameters"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vehicle",
            name="scoring_version",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="au_launch",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="price_type",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="research_status",
            field=models.CharField(blank=True, db_index=True, max_length=50),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="source_name",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="internal_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="source_tab",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="cost_category",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="energy_type",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="finance_apr_pct",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="total_interest_5yr",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="finance_fees_5yr",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="finance_cost_5yr",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="retention_factor",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="drivetrain",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="fuel_tank_l",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="range_battery_km",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="range_petrol_km",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="range_total_km",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="range_basis",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="range_ladder_step",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="range_estimated_badge",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="range_prior_value",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="price_basis",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="fe_basis",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="co2_basis",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="assumption_fills",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="data_flags",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="range_research_note",
            field=models.TextField(blank=True),
        ),
    ]
