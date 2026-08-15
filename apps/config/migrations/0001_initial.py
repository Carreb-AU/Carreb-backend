# Generated manually: initial SiteConfig singleton model

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='SiteConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('site_name', models.CharField(default='Carreb', max_length=255)),
                ('default_meta_title', models.CharField(default='Carreb — Estimated 5-Year Cost to Own Any New Car in Australia', max_length=255)),
                ('default_meta_description', models.TextField(default='Compare the true cost of owning any new car in Australia with Carreb.')),
                ('canonical_host', models.CharField(default='https://www.carreb.com.au', max_length=255)),
                ('ga4_measurement_id', models.CharField(blank=True, default='G-XXXXXXXXXX', help_text='Real GA4 measurement ID, e.g. G-ABCDEF1234', max_length=50)),
                ('legal_effective_date', models.DateField(blank=True, help_text='Effective date shown on ToS, Privacy, Cookie Policy and Vehicle Data Sources pages.', null=True)),
                ('homepage_vehicle_count_claim', models.CharField(default='3,000+', help_text='Claim shown on the homepage/registration page, e.g. "3,000+ New vehicles rated".', max_length=50)),
                ('organization_json_ld', models.JSONField(blank=True, default=dict, help_text='Organization JSON-LD object injected into the site head.')),
                ('extra_head_tags', models.TextField(blank=True, default='', help_text='Raw HTML tags to inject into <head> (e.g. Search Console verification).')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Site Configuration',
                'verbose_name_plural': 'Site Configuration',
            },
        ),
    ]
