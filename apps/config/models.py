from django.db import models


class SingletonBaseModel(models.Model):
    """Abstract base model that enforces a single configuration row."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SiteConfig(SingletonBaseModel):
    """
    Editable site-wide configuration. The client can change GA4 IDs, legal-page
    dates, default metadata and homepage numeric claims here without a deploy.
    """

    # Identity
    site_name = models.CharField(max_length=255, default='Carreb')

    # SEO / discoverability
    default_meta_title = models.CharField(
        max_length=255,
        default='Carreb — Estimated 5-Year Cost to Own Any New Car in Australia',
    )
    default_meta_description = models.TextField(
        default='Compare the true cost of owning any new car in Australia with Carreb.',
    )
    canonical_host = models.CharField(
        max_length=255,
        default='https://www.carreb.com.au',
    )

    # Analytics
    ga4_measurement_id = models.CharField(
        max_length=50,
        blank=True,
        default='G-XXXXXXXXXX',
        help_text='Real GA4 measurement ID, e.g. G-ABCDEF1234',
    )

    # Legal / compliance
    legal_effective_date = models.DateField(
        null=True,
        blank=True,
        help_text='Effective date shown on ToS, Privacy, Cookie Policy and Vehicle Data Sources pages.',
    )

    # Homepage / marketing claims
    homepage_vehicle_count_claim = models.CharField(
        max_length=50,
        default='3,000+',
        help_text='Claim shown on the homepage/registration page, e.g. "3,000+ New vehicles rated".',
    )

    # Structured data
    organization_json_ld = models.JSONField(
        default=dict,
        blank=True,
        help_text='Organization JSON-LD object injected into the site head.',
    )

    # Extra head tags (verification tags, etc.)
    extra_head_tags = models.TextField(
        blank=True,
        default='',
        help_text='Raw HTML tags to inject into <head> (e.g. Search Console verification).',
    )

    # Timestamps
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Site Configuration'
        verbose_name_plural = 'Site Configuration'

    def __str__(self):
        return self.site_name
