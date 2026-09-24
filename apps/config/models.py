import uuid
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


class PlatformDefault(models.Model):
    """
    Platform-wide global calculation parameters from PlatformDefaults tab (Carreb Calc v6.4).
    Controls PHEV electric ratio, slider defaults, star rating thresholds, and comparison windows.
    """
    config_key = models.CharField(max_length=100, unique=True)
    config_value = models.TextField()
    config_type = models.CharField(max_length=50, default='string')  # decimal, integer, string
    source_label = models.CharField(max_length=255, blank=True)
    last_updated = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['config_key']
        verbose_name = 'Platform Default'
        verbose_name_plural = 'Platform Defaults'

    def __str__(self):
        return f"{self.config_key} = {self.config_value}"

    @classmethod
    def get_val(cls, key: str, default=None):
        try:
            obj = cls.objects.get(config_key=key)
            if obj.config_type == 'decimal':
                return float(obj.config_value)
            elif obj.config_type == 'integer':
                return int(float(obj.config_value))
            return obj.config_value
        except cls.DoesNotExist:
            return default


class BuildChangelog(models.Model):
    """
    Audit log of system build & calculation changes across Carreb releases.
    Sourced from ChangesFromPriorBuild tab (Carreb Calc v6.4).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.CharField(max_length=255)
    prior_build = models.TextField(help_text="Prior build value/behavior")
    now_final = models.TextField(help_text="Current final release value/behavior")
    spec_source = models.CharField(max_length=255, blank=True, help_text="Spec section or sign-off reference")
    order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'item']
        verbose_name = 'Build Changelog'
        verbose_name_plural = 'Build Changelogs'

    def __str__(self):
        return f"{self.item}: {self.now_final[:50]}"


class ReleaseSummaryMetric(models.Model):
    """
    Key operational, architectural, and methodology metrics from v6.3.4 Summary tab (Carreb Calc v6.4).
    Contains core dataset counts, median COO by mode, finance defaults, star distributions, and reconciliation gaps.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section = models.CharField(max_length=100, help_text="e.g. CORE METRICS, CORE MODE, FINANCE DEFAULTS, SCORING, STAR DISTRIBUTION")
    metric = models.CharField(max_length=255)
    value = models.TextField(blank=True, default='')
    order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'section', 'metric']
        verbose_name = 'Release Summary Metric'
        verbose_name_plural = 'Release Summary Metrics'

    def __str__(self):
        return f"[{self.section}] {self.metric}: {self.value[:40]}"


class ACLComplianceRule(models.Model):
    """
    Australian Consumer Law (ACL) compliance rules & copywriting guardrails (Sheet: ACL_Disclaimer).
    Enforces mandatory language, banned phrases, mode-basis disclosures, and ACCC substantiation rules.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule_key = models.CharField(max_length=100, unique=True, help_text="e.g. Purpose, Required language, Banned phrases")
    rule_text = models.TextField(help_text="Compliance guidance or constraint")
    order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'rule_key']
        verbose_name = 'ACL Compliance Rule'
        verbose_name_plural = 'ACL Compliance Rules'

    def __str__(self):
        return f"{self.rule_key}: {self.rule_text[:50]}"


class SubstantiationSourceRegistry(models.Model):
    """
    Master Sources & ACCC Substantiation Index from Sheet 22 (_Sources_Index).
    Documents the primary source, publisher, data period, refresh cadence, and ACCC substantiation class
    for every calculation component, table, and policy parameter across the Carreb platform.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    data_category = models.CharField(max_length=255, unique=True, help_text="e.g. FCAI segmentation, Petrol price by state, CTP insurance by state")
    carreb_table_or_sheet = models.CharField(max_length=255, help_text="Internal model or workbook sheet reference")
    primary_source = models.TextField(help_text="Primary data publisher or regulatory authority")
    url_or_publisher = models.TextField(blank=True, help_text="URLs or publisher citation")
    data_period_in_dump = models.CharField(max_length=100, blank=True, help_text="e.g. Mar 2026, 2025-26, Oct 2024")
    refresh_cadence = models.CharField(max_length=100, blank=True, help_text="e.g. Annually, Monthly, Quarterly, On policy change")
    accc_substantiation_class = models.TextField(blank=True, help_text="ACCC legal substantiation classification")
    order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'data_category']
        verbose_name = 'Substantiation Source'
        verbose_name_plural = 'Substantiation Sources Index'

    def __str__(self):
        return f"{self.data_category} ({self.primary_source})"

    @classmethod
    def get_source_for_category(cls, category: str):
        return cls.objects.filter(data_category__iexact=category.strip()).first()


class PolicyUpdateLog(models.Model):
    """
    Policy and regulatory update audit ledger from Sheet 25 (v6.4 Policy Update Log).
    Documents statutory changes in energy tariffs, tax thresholds, legal rulings (Vanderstock 2023),
    interest rate adjustments, and state EV subsidy statuses at the v6.4 Launch (10-Jul-26).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item_number = models.IntegerField(default=0, help_text="Item number from workbook")
    parameter = models.CharField(max_length=255, help_text="Parameter or policy rule name")
    tab_affected = models.CharField(max_length=100, help_text="Workbook sheet or DB table affected")
    old_value = models.TextField(blank=True, help_text="Prior value or behavior")
    new_value = models.TextField(blank=True, help_text="Updated value at 2026-07-10")
    effective_date = models.CharField(max_length=100, blank=True)
    source = models.CharField(max_length=255, blank=True)
    spec_ref = models.CharField(max_length=100, blank=True)
    reason = models.TextField(blank=True, help_text="Statutory ruling, regulatory decision, or economic rationale")
    status = models.CharField(max_length=50, default='APPLIED', help_text="e.g. APPLIED, NOTED, FLAGGED, CONFIRM")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['item_number', 'parameter']
        verbose_name = 'Policy Update Log'
        verbose_name_plural = 'Policy Update Logs'

    def __str__(self):
        return f"#{self.item_number} {self.parameter}: {self.new_value[:40]} [{self.status}]"


class DevSpecTraceMap(models.Model):
    """
    Developer Specification & System Architecture Traceability Matrix from Sheet 26 (DevSpec_TraceMap).
    Maps every workbook dataset, tab, and calculation feed to its governing Developer Spec (§) section,
    Calculation Spec (§) section, authoritative Source of Truth, and engine/UI consumer endpoints.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item_number = models.IntegerField(default=0, help_text="Sequence number from workbook")
    workbook_tab = models.CharField(max_length=100, unique=True, help_text="Source workbook tab name")
    feeds = models.CharField(max_length=255, help_text="System consumers e.g. UI / engine / catalogue / MyGarage")
    dev_spec_section = models.CharField(max_length=100, blank=True, help_text="Developer Spec section reference e.g. §3 Domain")
    calc_spec_section = models.CharField(max_length=100, blank=True, help_text="Calculation Spec section reference e.g. §2.2")
    source_of_truth = models.CharField(max_length=100, blank=True, help_text="Authoritative source e.g. GVG / ADR, Batch engine, Seed JSON")
    notes = models.TextField(blank=True, help_text="Implementation, stale flag, or re-batch notes")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['item_number', 'workbook_tab']
        verbose_name = 'Dev Spec Trace Map'
        verbose_name_plural = 'Dev Spec Trace Maps'

    def __str__(self):
        return f"#{self.item_number} {self.workbook_tab} -> {self.feeds}"






