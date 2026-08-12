# Trigram type-ahead for GreenVehicleGuideRecord search

import django.contrib.postgres.indexes
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations, models


def populate_search_text(apps, schema_editor):
    GreenVehicleGuideRecord = apps.get_model('vehicles', 'GreenVehicleGuideRecord')
    for record in GreenVehicleGuideRecord.objects.all().iterator():
        record.search_text = ' '.join(p for p in [str(record.year), record.make, record.model, record.variant] if p).lower()
        record.save(update_fields=['search_text'])


def reverse_populate(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0006_datasource_categorycostdefault_greenvehicleguiderecord'),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddField(
            model_name='greenvehicleguiderecord',
            name='search_text',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.RunPython(populate_search_text, reverse_populate),
        migrations.AddIndex(
            model_name='greenvehicleguiderecord',
            index=django.contrib.postgres.indexes.GinIndex(
                fields=['search_text'],
                name='gvg_search_trgm_idx',
                opclasses=['gin_trgm_ops'],
            ),
        ),
    ]
