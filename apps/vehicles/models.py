import uuid
from django.db import models
from django.contrib.postgres.indexes import GinIndex
from django.utils.translation import gettext_lazy as _

class PowertrainType(models.TextChoices):
    PETROL = 'petrol', 'Petrol'
    DIESEL = 'diesel', 'Diesel'
    MILD_HYBRID = 'mild_hybrid', 'Mild Hybrid'
    HYBRID = 'hybrid', 'Hybrid'
    PHEV = 'phev', 'Plug-in Hybrid (PHEV)'
    BEV = 'bev', 'Battery Electric (BEV)'
    FCEV = 'fcev', 'Hydrogen / FCEV'

class TestCycle(models.TextChoices):
    WLTP = 'WLTP', 'WLTP'
    ADR = 'ADR', 'ADR'
    NEDC = 'NEDC', 'NEDC'


class DataSource(models.Model):
    """
    Registry for external data sources used to substantiate vehicle specs.
    """
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    url = models.URLField(blank=True)
    dataset_type = models.CharField(max_length=50, blank=True)
    retrieved_at = models.DateTimeField(null=True, blank=True)
    archived_file = models.FileField(upload_to='data/source_archives/', blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} — {self.name}"


class CategoryCostDefault(models.Model):
    """
    Per-FCAI-category, per-state default cost components used when a GVG
    record does not have a matching Carreb catalogue row.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fcai_category = models.CharField(max_length=100)
    fcai_broad = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=10)
    annual_km = models.IntegerField(default=13300)

    ctp_pa = models.IntegerField(null=True, blank=True)               # cents
    comprehensive_pa = models.IntegerField(null=True, blank=True)     # cents
    registration_pa = models.IntegerField(null=True, blank=True)      # cents
    maintenance_pa = models.IntegerField(null=True, blank=True)         # cents p.a.
    tyre_cost_pa = models.IntegerField(null=True, blank=True)          # cents p.a.
    fuel_cost_pa = models.IntegerField(null=True, blank=True)         # cents p.a.
    electricity_cost_pa = models.IntegerField(null=True, blank=True)  # cents p.a.
    ev_levy_pa = models.IntegerField(null=True, blank=True)            # cents p.a.
    components_sum_pa = models.IntegerField(null=True, blank=True)    # cents p.a.

    servicing_5yr_estimate = models.IntegerField(null=True, blank=True)
    tyre_replacement_estimate = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fcai_category', 'state']
        unique_together = ['fcai_category', 'state']

    def __str__(self):
        return f"{self.fcai_category} — {self.state}"


class CategoryScoringBounds(models.Model):
    """
    IQR-trimmed scoring bounds and vehicle counts per (fcai_category × core_mode)
    from CategoryScoringBounds tab in Carreb Calc Workbook v6.4.
    Used for live CORE score normalization and outlier exclusion.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fcai_category = models.CharField(max_length=100)
    core_mode = models.CharField(max_length=10)  # B, C, E, F
    vehicle_count = models.IntegerField(default=0)

    cat_min_coo = models.FloatField()
    cat_max_coo = models.FloatField()
    actual_min_coo = models.FloatField(null=True, blank=True)
    actual_max_coo = models.FloatField(null=True, blank=True)

    cat_min_co2 = models.FloatField(default=0.0)
    cat_max_co2 = models.FloatField(default=0.0)
    scoring_version = models.CharField(max_length=50, default='v6.3.4-cat-norm')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fcai_category', 'core_mode']
        unique_together = ['fcai_category', 'core_mode', 'scoring_version']
        verbose_name = 'Category Scoring Bounds'
        verbose_name_plural = 'Category Scoring Bounds'

    def __str__(self):
        return f"{self.fcai_category} [Mode {self.core_mode}] ({self.scoring_version})"


class FinanceDefault(models.Model):
    """
    Finance parameters per broad vehicle category from FinanceDefaults tab (Carreb Calc v6.4).
    Powers Mode E (Cool Choice) and Mode F (Full Picture) finance calculations.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fcai_category_broad = models.CharField(max_length=100, unique=True)
    deposit_pct = models.FloatField(default=10.0)
    base_rate_pct = models.FloatField(default=7.5)
    alt_fuel_modifier_pct = models.FloatField(default=-1.5)
    term_months = models.IntegerField(default=60)
    balloon_pct = models.FloatField(default=0.0)
    estab_fee_default = models.IntegerField(default=40000)  # cents
    estab_fee_bev = models.IntegerField(default=30000)      # cents
    admin_fee_monthly = models.IntegerField(default=1000)   # cents
    effective_from = models.DateField(null=True, blank=True)
    source = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fcai_category_broad']
        verbose_name = 'Finance Default'
        verbose_name_plural = 'Finance Defaults'

    def __str__(self):
        return f"{self.fcai_category_broad} ({self.base_rate_pct}%)"


class VehicleIdentity(models.Model):
    """
    Imported GVG / Fuel Consumption Guide data for prior-year current-vehicle lookup.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(DataSource, on_delete=models.SET_NULL, null=True, blank=True)

    # Identity
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    year = models.IntegerField()
    variant = models.CharField(max_length=255, blank=True)

    # Specs
    body_style = models.CharField(max_length=100, blank=True)
    fcai_category = models.CharField(max_length=100, blank=True)
    fcai_broad = models.CharField(max_length=100, blank=True)
    powertrain_type = models.CharField(max_length=50, choices=PowertrainType.choices, blank=True)
    fuel_type_raw = models.CharField(max_length=100, blank=True)

    engine_l = models.FloatField(null=True, blank=True)
    battery_kwh = models.FloatField(null=True, blank=True)
    num_seats = models.IntegerField(null=True, blank=True)
    drive = models.CharField(max_length=50, blank=True, default='')
    transmission = models.CharField(max_length=100, blank=True)
    tow_braked_kg = models.IntegerField(null=True, blank=True)
    tow_unbraked_kg = models.IntegerField(null=True, blank=True)
    sales_status = models.CharField(max_length=50, blank=True, default='')
    price_type = models.CharField(max_length=50, blank=True, default='')
    price_state = models.CharField(max_length=10, blank=True, default='')
    price_as_at = models.DateField(null=True, blank=True)

    # Consumption / emissions
    fuel_consumption_combined_l_100km = models.FloatField(null=True, blank=True)
    fuel_consumption_urban_l_100km = models.FloatField(null=True, blank=True)
    fuel_consumption_extra_urban_l_100km = models.FloatField(null=True, blank=True)
    electricity_consumption_wh_per_km = models.FloatField(null=True, blank=True)
    electric_range_km = models.FloatField(null=True, blank=True)
    tailpipe_co2_g_per_km = models.FloatField(null=True, blank=True)

    # Cost discipline
    annual_fuel_cost = models.IntegerField(null=True, blank=True)  # cents
    driveaway_price_estimate = models.IntegerField(null=True, blank=True)  # cents
    insurance_estimate_by_state = models.JSONField(default=dict, blank=True)
    ctp_by_state = models.JSONField(default=dict, blank=True)
    registration_by_state = models.JSONField(default=dict, blank=True)
    servicing_5yr_estimate = models.IntegerField(null=True, blank=True)  # cents
    tyre_replacement_estimate = models.IntegerField(null=True, blank=True)  # cents
    resale_value_5yr_estimate = models.IntegerField(null=True, blank=True)  # cents
    total_5yr_cost_of_ownership_by_state = models.JSONField(default=dict, blank=True)

    # Source discipline
    is_current_model = models.BooleanField(null=True, blank=True)
    model_end_year = models.IntegerField(null=True, blank=True)
    test_cycle = models.CharField(max_length=50, blank=True)
    source_dataset = models.CharField(max_length=50, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    provenance = models.JSONField(default=dict, blank=True)
    # Example:
    # {
    #   "source_id": "<uuid>",
    #   "source_code": "S-GVG-CURRENT",
    #   "source_name": "Green Vehicle Guide — Vehicles 2004-2025",
    #   "source_url": "https://greenvehicleguide.gov.au",
    #   "retrieved_at": "2026-08-14T00:00:00Z",
    #   "archived_file": "data/source_archives/S-GVG-CURRENT.xlsx",
    #   "dataset_type": "xlsx",
    #   "test_cycle": "ADR"
    # }

    # Media
    image_url = models.URLField(max_length=2000, blank=True, null=True)

    # Fuzzy type-ahead support (trigram GIN index). Maintained automatically by save().
    search_text = models.TextField(blank=True, default='')

    imported_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['make', 'model', 'year', 'variant']
        indexes = [
            models.Index(fields=['make', 'model', 'year']),
            models.Index(fields=['powertrain_type']),
            models.Index(fields=['fcai_category']),
            GinIndex(fields=['search_text'], name='vehicle_identity_search_idx', opclasses=['gin_trgm_ops']),
        ]

    def build_search_text(self):
        return ' '.join(p for p in [str(self.year), self.make, self.model, self.variant] if p).lower()

    def save(self, *args, **kwargs):
        self.search_text = self.build_search_text()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.year} {self.make} {self.model} {self.variant}"


class Vehicle(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    brand = models.CharField(max_length=255)
    model = models.CharField(max_length=255)
    year = models.IntegerField()
    variant = models.CharField(max_length=255)
    body_style = models.CharField(max_length=100)
    image_url = models.URLField(max_length=2000, blank=True, null=True)
    num_seats = models.IntegerField(default=5)
    powertrain_type = models.CharField(max_length=50, choices=PowertrainType.choices)
    fcai_category = models.CharField(max_length=100)
    fcai_broad = models.CharField(max_length=100, blank=True)
    energy_norm = models.CharField(max_length=50, blank=True)
    drive = models.CharField(max_length=50, blank=True)
    engine_l = models.FloatField(null=True, blank=True)
    battery_kwh = models.FloatField(null=True, blank=True)
    tow_braked_kg = models.IntegerField(null=True, blank=True)
    tow_unbraked_kg = models.IntegerField(null=True, blank=True)
    
    ancap_safety_rating = models.IntegerField(null=True, blank=True)
    ancap_tested_year = models.IntegerField(null=True, blank=True)
    driveaway_price_by_state = models.JSONField(default=dict)
    
    fuel_consumption_per_100km = models.FloatField(null=True, blank=True)
    electricity_consumption_per_100km = models.FloatField(null=True, blank=True)
    tailpipe_co2_g_per_km = models.FloatField(null=True, blank=True)
    wltp_range_km = models.FloatField(null=True, blank=True)
    test_cycle = models.CharField(max_length=20, choices=TestCycle.choices)
    
    annual_km_default = models.IntegerField(default=13300)
    insurance_estimate_by_state = models.JSONField(default=dict)
    ctp_by_state = models.JSONField(default=dict)
    registration_by_state = models.JSONField(default=dict)
    servicing_5yr_estimate = models.IntegerField(null=True, blank=True)
    tyre_replacement_estimate = models.IntegerField(null=True, blank=True)
    resale_value_5yr_estimate = models.IntegerField(null=True, blank=True)
    total_5yr_cost_of_ownership_by_state = models.JSONField(default=dict)
    
    fuel_cost_by_state = models.JSONField(default=dict)
    electricity_cost_by_state = models.JSONField(default=dict)
    ev_levy_by_state = models.JSONField(default=dict)
    base_coo_by_state = models.JSONField(default=dict)
    components_sum_by_state = models.JSONField(default=dict)
    
    mode_data_by_state = models.JSONField(default=dict)
    is_scoring_outlier = models.BooleanField(default=False)
    scoring_version = models.CharField(max_length=100, blank=True)

    # Consolidated Vehicles v6.4 sheet — lineage & research fields
    au_launch = models.CharField(max_length=50, blank=True)
    price_type = models.CharField(max_length=100, blank=True)
    research_status = models.CharField(max_length=50, blank=True, db_index=True)
    source_name = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    source_tab = models.CharField(max_length=50, blank=True)

    # Consolidated Vehicles v6.4 sheet — cost & range provenance fields
    cost_category = models.CharField(max_length=100, blank=True)
    energy_type = models.CharField(max_length=50, blank=True)
    finance_apr_pct = models.FloatField(null=True, blank=True)
    total_interest_5yr = models.IntegerField(null=True, blank=True)  # cents
    finance_fees_5yr = models.IntegerField(null=True, blank=True)  # cents
    finance_cost_5yr = models.IntegerField(null=True, blank=True)  # cents
    retention_factor = models.FloatField(null=True, blank=True)
    drivetrain = models.CharField(max_length=50, blank=True)
    fuel_tank_l = models.FloatField(null=True, blank=True)
    range_battery_km = models.FloatField(null=True, blank=True)
    range_petrol_km = models.FloatField(null=True, blank=True)
    range_total_km = models.FloatField(null=True, blank=True)
    range_basis = models.TextField(blank=True)
    range_ladder_step = models.IntegerField(null=True, blank=True)
    range_estimated_badge = models.BooleanField(default=False)
    range_prior_value = models.FloatField(null=True, blank=True)
    price_basis = models.CharField(max_length=255, blank=True)
    fe_basis = models.CharField(max_length=255, blank=True)
    co2_basis = models.CharField(max_length=255, blank=True)
    assumption_fills = models.TextField(blank=True)
    data_flags = models.TextField(blank=True)
    range_research_note = models.TextField(blank=True)

    # 13-Oct-26 workbook additions
    co2_energy_cycle_g_per_km = models.FloatField(null=True, blank=True)
    spotlight_data = models.JSONField(default=dict, blank=True)
    # spotlight_data example (one row per vehicle in the "Spotlights" sheet,
    # computed on a NSW / Mode B basis):
    # {
    #   "range_kings": True, "green_lean": True, "unicorn_match": True,
    #   "category_sweep": True, "core_allstars": True, "count": 5,
    #   "badges": "Range Kings™, Green & Lean™, …",
    #   "version": "v6.4-derived-percentile (Mode B, category-aware)"
    # }

    provenance = models.JSONField(default=dict)
    # Example:
    # {
    #   "brand": {"source_category": "Manufacturer", "retrieved_at": "2026-01-01T00:00:00Z"},
    #   "fuel_consumption_per_100km": {"source_category": "GVG", "retrieved_at": "2026-01-01T00:00:00Z"}
    # }

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['brand', 'model', 'year', 'variant']

    def __str__(self):
        return f"{self.year} {self.brand} {self.model} {self.variant}"


class ManualVehicleEnrichment(models.Model):
    """
    Admin-curated enrichment for GVG / legacy records. Used when the original
    source lacks a field (e.g. engine_l, ANCAP, image_url). Each field carries
    its own provenance badge (S-CARREB-MANUAL) so the citation chain is intact.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.OneToOneField(
        VehicleIdentity,
        on_delete=models.CASCADE,
        related_name='manual_enrichment',
    )

    engine_l = models.FloatField(null=True, blank=True)
    ancap_safety_rating = models.IntegerField(null=True, blank=True)
    ancap_tested_year = models.IntegerField(null=True, blank=True)
    image_url = models.URLField(max_length=2000, blank=True, null=True)
    driveaway_price_estimate = models.IntegerField(null=True, blank=True)  # cents
    resale_value_5yr_estimate = models.IntegerField(null=True, blank=True)  # cents
    notes = models.TextField(blank=True, default='')

    enriched_by = models.CharField(max_length=255, blank=True)
    enriched_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Manual Vehicle Enrichment'
        verbose_name_plural = 'Manual Vehicle Enrichments'

    def __str__(self):
        return f"Manual enrichment for {self.record}"


class EnergyTypeModifier(models.Model):
    """
    Multipliers applied to CategoryCostDefault benchmark components based on
    powertrain type (Spec §3.5). All defaults are 1.0 so an unseeded table is
    safe; admins tune from real data over time.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    powertrain_type = models.CharField(
        max_length=50,
        choices=PowertrainType.choices,
        unique=True,
    )

    fuel_cost_multiplier = models.FloatField(default=1.0)
    electricity_cost_multiplier = models.FloatField(default=1.0)
    servicing_cost_multiplier = models.FloatField(default=1.0)
    tyre_cost_multiplier = models.FloatField(default=1.0)
    insurance_cost_multiplier = models.FloatField(default=1.0)
    registration_cost_multiplier = models.FloatField(default=1.0)

    resale_value_multiplier = models.FloatField(default=1.0)
    retention_multiplier = models.FloatField(default=1.0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Energy Type Modifier'
        verbose_name_plural = 'Energy Type Modifiers'

    def __str__(self):
        return f"{self.get_powertrain_type_display()} modifiers"


class DepreciationBrandModifier(models.Model):
    """
    Per-brand modifiers applied to depreciation / resale estimates (Spec §3.5).
    A multiplier >1 means stronger-than-average resale / retention.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.CharField(max_length=255, unique=True)

    retention_multiplier = models.FloatField(default=1.0)
    resale_value_multiplier = models.FloatField(default=1.0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Depreciation Brand Modifier'
        verbose_name_plural = 'Depreciation Brand Modifiers'

    def __str__(self):
        return f"{self.brand} depreciation modifiers"


class DepreciationLookup(models.Model):
    """
    3-Layer Depreciation Lookup benchmarks from Carreb Calc Workbook v6.4 (Sheet: DepreciationLookups).
    Layer 1: Category Base Retention (5yr) - Baseline retention % per vehicle category
    Layer 2: Energy Type Modifier - Multiplier per powertrain/energy type
    Layer 3: Brand Modifier - Brand retention multiplier segmented by powertrain or default
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    layer = models.CharField(max_length=100, help_text="e.g. Layer 1: Category Base Retention (5yr)")
    layer_num = models.IntegerField(help_text="1, 2, or 3")
    key = models.CharField(max_length=100, help_text="Category name, energy type, or brand name")
    powertrain_type = models.CharField(max_length=50, blank=True, default='', help_text="Powertrain qualifier (e.g. electric, hybrid, petrol, diesel, phev, default)")
    modifier = models.FloatField(help_text="Decimal rate or multiplier (e.g. 0.45 for 45% retention, 1.15 for +15% modifier)")
    source = models.CharField(max_length=255, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['layer_num', 'layer', 'key']
        verbose_name = 'Depreciation Lookup'
        verbose_name_plural = 'Depreciation Lookups'
        constraints = [
            models.UniqueConstraint(fields=['layer', 'key'], name='unique_depreciation_layer_key')
        ]

    def __str__(self):
        return f"[{self.layer}] {self.key}: {self.modifier}"

    @classmethod
    def get_category_retention(cls, category: str) -> float:
        """Return 5-year base retention rate for vehicle category (default 0.40)."""
        row = cls.objects.filter(layer_num=1, key__iexact=category.strip()).first()
        if not row:
            row = cls.objects.filter(layer_num=1, key__iexact='Other').first()
        return row.modifier if row else 0.40

    @classmethod
    def get_energy_modifier_val(cls, powertrain: str) -> float:
        """Return Layer 2 energy type multiplier (default 1.0)."""
        if not powertrain:
            return 1.0
        row = cls.objects.filter(layer_num=2, key__iexact=powertrain.strip()).first()
        if not row:
            row = cls.objects.filter(layer_num=2, key__iexact='unknown').first()
        return row.modifier if row else 1.0

    @classmethod
    def get_brand_modifier_val(cls, brand: str, powertrain: str = '') -> float:
        """Return Layer 3 brand multiplier by powertrain or generic fallback (default 1.0)."""
        if not brand:
            return 1.0
        brand_clean = brand.strip().lower()
        powertrain_clean = (powertrain or '').strip().lower()

        # 1. Exact match on brand + powertrain qualifier
        if powertrain_clean:
            row = cls.objects.filter(
                layer_num=3,
                key__iexact=brand_clean,
                powertrain_type__iexact=powertrain_clean,
            ).first()
            if row:
                return row.modifier

        # 2. Match on brand with default / generic powertrain
        row = cls.objects.filter(
            layer_num=3,
            key__iexact=brand_clean,
        ).first()
        if row:
            return row.modifier

        # 3. Fallback to *generic* default
        generic = cls.objects.filter(layer_num=3, key='*generic*').first()
        return generic.modifier if generic else 1.0

    @classmethod
    def calculate_5yr_retention(cls, category: str, powertrain: str, brand: str) -> float:
        """Compute the combined 3-layer 5-year retention rate."""
        l1 = cls.get_category_retention(category)
        l2 = cls.get_energy_modifier_val(powertrain)
        l3 = cls.get_brand_modifier_val(brand, powertrain)
        return l1 * l2 * l3


class FCAICategoryRegistry(models.Model):
    """
    Official 27 FCAI VFACTS vehicle categories and their Carreb DB canonical mappings (Sheet: FCAICategoryRegistry).
    Maps market segments, price thresholds, broad vehicle classes, and representative vehicle benchmarks.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    segment_id = models.IntegerField(unique=True, help_text="1 to 27 sequence number from VFACTS")
    fcai_segment = models.CharField(max_length=150, unique=True, help_text="e.g. Small (under $40,000)")
    carreb_db_label = models.CharField(max_length=100, db_index=True, help_text="e.g. Small, Small-Premium")
    vehicle_class = models.CharField(max_length=50, help_text="Passenger, SUV, Light Commercial")
    representative_vehicles = models.TextField(blank=True, default='', help_text="Benchmark vehicle examples")
    criteria_notes = models.TextField(blank=True, default='', help_text="Segmentation threshold notes")
    source = models.CharField(max_length=255, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['segment_id']
        verbose_name = 'FCAI Category Registry'
        verbose_name_plural = 'FCAI Category Registries'

    def __str__(self):
        return f"#{self.segment_id} {self.fcai_segment} -> {self.carreb_db_label} ({self.vehicle_class})"

    @classmethod
    def get_carreb_label_for_segment(cls, segment_name: str) -> str:
        """Map official FCAI segment name to Carreb canonical DB label."""
        row = cls.objects.filter(fcai_segment__iexact=segment_name.strip()).first()
        return row.carreb_db_label if row else segment_name


class StateEnergyPrice(models.Model):
    """
    State-by-state fuel and electricity retail price benchmarks (Sheet: FuelElectricityPrices).
    Powers fuel and electricity running cost calculations across all powertrains (ICE, EV, PHEV, FCEV).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state = models.CharField(max_length=20, unique=True, help_text="State code (NSW, VIC, QLD, SA, WA, TAS, NT, ACT) or 'National Avg'")
    petrol_ulp95_cents_per_litre = models.IntegerField(null=True, blank=True, help_text="ULP95 retail price in whole cents per litre (e.g. 244 for $2.44/L)")
    diesel_cents_per_litre = models.IntegerField(null=True, blank=True, help_text="Diesel retail price in whole cents per litre (e.g. 305 for $3.05/L)")
    electricity_cents_per_kwh = models.FloatField(null=True, blank=True, help_text="Electricity retail rate in cents per kWh (e.g. 27.5 for $0.275/kWh)")
    data_period = models.CharField(max_length=100, blank=True, default='')
    source = models.CharField(max_length=255, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['state']
        verbose_name = 'State Energy Price'
        verbose_name_plural = 'State Energy Prices'

    def __str__(self):
        return f"{self.state} (Petrol: {self.petrol_ulp95_cents_per_litre}c/L, Diesel: {self.diesel_cents_per_litre}c/L, Elec: {self.electricity_cents_per_kwh}c/kWh)"

    @classmethod
    def get_price_for_state(cls, state: str):
        """Fetch energy price benchmark for state with fallback to National Avg."""
        clean_state = state.strip().upper() if state else 'NATIONAL AVG'
        row = cls.objects.filter(state__iexact=clean_state).first()
        if not row:
            row = cls.objects.filter(state__iexact='National Avg').first()
        return row


class CTPStateDefault(models.Model):
    """
    Compulsory Third Party (CTP) insurance defaults by state from Section A (Sheet: InsuranceDefaults).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state = models.CharField(max_length=20, unique=True, help_text="State code (NSW, VIC, QLD, SA, WA, TAS, NT, ACT)")
    annual_ctp_cents = models.IntegerField(help_text="Annual CTP in whole cents (e.g. 67500 for $675)")
    bundled_in_rego = models.CharField(max_length=50, blank=True, help_text="Whether CTP is included in registration payment")
    notes = models.TextField(blank=True)
    source = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['state']
        verbose_name = 'CTP State Default'
        verbose_name_plural = 'CTP State Defaults'

    def __str__(self):
        return f"{self.state} CTP: {self.annual_ctp_cents}c ({self.bundled_in_rego})"


class InsuranceCategoryBenchmark(models.Model):
    """
    Comprehensive insurance national averages by vehicle category from Section B (Sheet: InsuranceDefaults).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fcai_category = models.CharField(max_length=100, unique=True, help_text="FCAI vehicle category name")
    national_avg_cents_pa = models.IntegerField(help_text="National average annual comprehensive premium in cents")
    estimated_monthly_cents = models.IntegerField(help_text="Estimated monthly comprehensive premium in cents")
    representative_basis = models.TextField(blank=True, help_text="Benchmark vehicle examples and risk notes")
    source = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fcai_category']
        verbose_name = 'Insurance Category Benchmark'
        verbose_name_plural = 'Insurance Category Benchmarks'

    def __str__(self):
        return f"{self.fcai_category}: {self.national_avg_cents_pa}c p.a."

    @classmethod
    def get_comprehensive_cents(cls, category: str, state: str) -> int:
        """Compute state-specific comprehensive insurance premium in cents (Section D matrix formula)."""
        cat_row = cls.objects.filter(fcai_category__iexact=category.strip()).first()
        if not cat_row:
            cat_row = cls.objects.filter(fcai_category__iexact='Medium').first()
        if not cat_row:
            return 111600

        mod_row = InsuranceStateModifier.objects.filter(state__iexact=state.strip()).first()
        multiplier = mod_row.state_modifier if mod_row else 1.0
        return int(round(cat_row.national_avg_cents_pa * multiplier))


class InsuranceStateModifier(models.Model):
    """
    State risk modifier multipliers applied to national comprehensive averages from Section C (Sheet: InsuranceDefaults).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state = models.CharField(max_length=20, unique=True, help_text="State code (NSW, VIC, QLD, SA, WA, TAS, NT, ACT)")
    avg_comprehensive_cents = models.IntegerField(help_text="State average comprehensive premium in cents")
    national_avg_cents = models.IntegerField(help_text="National baseline benchmark in cents")
    state_modifier = models.FloatField(help_text="Multiplier relative to national benchmark (e.g. 1.178 for NSW, 1.510 for VIC)")
    relative_to_national = models.CharField(max_length=50, blank=True, help_text="e.g. +17.8%, +51.0%")
    explanation = models.TextField(blank=True)
    source = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['state']
        verbose_name = 'Insurance State Modifier'
        verbose_name_plural = 'Insurance State Modifiers'

    def __str__(self):
        return f"{self.state}: {self.state_modifier}x ({self.relative_to_national})"


class RegistrationCategoryBenchmark(models.Model):
    """
    Representative vehicle specifications used to derive state registration fees from Section A (Sheet: RegistrationDefaults).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fcai_category = models.CharField(max_length=100, unique=True, help_text="FCAI vehicle category name")
    representative_vehicle = models.CharField(max_length=255, help_text="Representative benchmark model (e.g. Toyota Corolla)")
    kerb_weight_kg = models.IntegerField(help_text="Kerb weight in kg")
    cylinders = models.IntegerField(null=True, blank=True, help_text="Engine cylinder count")
    engine_l = models.FloatField(null=True, blank=True, help_text="Engine displacement in litres")
    energy_type = models.CharField(max_length=50, default='ICE')
    total_avg_cents_pa = models.IntegerField(null=True, blank=True, help_text="National total average registration fee in whole cents")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fcai_category']
        verbose_name = 'Registration Category Benchmark'
        verbose_name_plural = 'Registration Category Benchmarks'

    def __str__(self):
        return f"{self.fcai_category}: {self.representative_vehicle} ({self.kerb_weight_kg}kg, {self.engine_l}L)"


class RegistrationFeeByState(models.Model):
    """
    Annual vehicle registration fees by FCAI category and state from Section B (Sheet: RegistrationDefaults).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fcai_category = models.CharField(max_length=100, help_text="FCAI vehicle category name")
    state = models.CharField(max_length=20, help_text="State code (NSW, VIC, QLD, SA, WA, TAS, NT, ACT)")
    annual_fee_cents = models.IntegerField(help_text="Annual registration fee in whole cents")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fcai_category', 'state']
        unique_together = ['fcai_category', 'state']
        verbose_name = 'Registration Fee By State'
        verbose_name_plural = 'Registration Fees By State'

    def __str__(self):
        return f"{self.fcai_category} in {self.state}: {self.annual_fee_cents}c p.a."

    @classmethod
    def get_fee_cents(cls, category: str, state: str) -> int:
        """Fetch exact registration fee in whole cents for given category and state."""
        row = cls.objects.filter(fcai_category__iexact=category.strip(), state__iexact=state.strip()).first()
        if not row:
            row = cls.objects.filter(fcai_category__iexact='Medium', state__iexact=state.strip()).first()
        return row.annual_fee_cents if row else 60000


class RegistrationStateFormula(models.Model):
    """
    Statutory registration fee calculation formulas and guidance notes by state from Section C (Sheet: RegistrationDefaults).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state = models.CharField(max_length=20, unique=True, help_text="State code (NSW, VIC, QLD, SA, WA, TAS, NT, ACT)")
    basis_notes = models.TextField(help_text="Statutory formula explanation and calculation rules")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['state']
        verbose_name = 'Registration State Formula'
        verbose_name_plural = 'Registration State Formulas'

    def __str__(self):
        return f"{self.state} Rego Formula: {self.basis_notes[:50]}"


class MaintenanceCategoryDefault(models.Model):
    """
    Standard scheduled servicing and maintenance cost benchmarks by FCAI category (Sheet: MaintenanceDefaults).
    Powers maintenance_pa and servicing_5yr_estimate in vehicle cost-of-ownership calculations.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fcai_category = models.CharField(max_length=100, unique=True, help_text="FCAI vehicle category name")
    representative_vehicle = models.CharField(max_length=255, help_text="Benchmark vehicle model")
    service_interval = models.CharField(max_length=100, help_text="e.g. 12mo / 15,000km")
    five_year_total_cents = models.IntegerField(help_text="5-year total scheduled servicing cost in whole cents")
    annual_avg_cents = models.IntegerField(help_text="Annual average scheduled servicing cost in whole cents")
    year1_cents = models.IntegerField(help_text="Year 1 servicing cost in whole cents")
    year5_cents = models.IntegerField(help_text="Year 5 servicing cost in whole cents")
    source = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fcai_category']
        verbose_name = 'Maintenance Category Default'
        verbose_name_plural = 'Maintenance Category Defaults'

    def __str__(self):
        return f"{self.fcai_category}: {self.annual_avg_cents}c p.a. ({self.service_interval})"

    @classmethod
    def get_maintenance_for_category(cls, category: str):
        """Fetch maintenance default benchmark for category with fallback to Medium."""
        row = cls.objects.filter(fcai_category__iexact=category.strip()).first()
        if not row:
            row = cls.objects.filter(fcai_category__iexact='Medium').first()
        return row


class TyreCategoryDefault(models.Model):
    """
    Standard tyre specifications, replacement intervals, and replacement costs by FCAI category (Sheet: TyreCostDefaults).
    Powers tyre_cost_pa and tyre_replacement_estimate in vehicle cost-of-ownership calculations.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fcai_category = models.CharField(max_length=100, unique=True, help_text="FCAI vehicle category name")
    typical_tyre_size = models.CharField(max_length=100, help_text="e.g. 205/55R16, 265/60R18 (A/T)")
    cost_per_set_4_cents = models.IntegerField(help_text="Cost for a complete set of 4 tyres in whole cents")
    replacement_interval_km = models.IntegerField(help_text="Expected tyre replacement interval in km")
    annualised_cost_cents = models.IntegerField(help_text="Annualised tyre replacement cost in whole cents")
    source = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fcai_category']
        verbose_name = 'Tyre Category Default'
        verbose_name_plural = 'Tyre Category Defaults'

    def __str__(self):
        return f"{self.fcai_category}: {self.typical_tyre_size} (${self.cost_per_set_4_cents/100:.0f}/set, {self.annualised_cost_cents}c p.a.)"

    @classmethod
    def get_tyre_for_category(cls, category: str):
        """Fetch tyre default benchmark for category with fallback to Medium."""
        row = cls.objects.filter(fcai_category__iexact=category.strip()).first()
        if not row:
            row = cls.objects.filter(fcai_category__iexact='Medium').first()
        return row


class EnergyTypeCostModifier(models.Model):
    """
    Cost component modifiers across energy and powertrain types from Sheet 18 (EnergyTypeCostModifiers).
    Covers Maintenance, Comprehensive Insurance, CTP, Tyre Wear, Tyre Cost, Rego, and State EV Levies.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cost_component = models.CharField(max_length=100, unique=True, help_text="e.g. Maintenance, Comprehensive Insurance, Tyre Wear Rate, etc.")
    ice_petrol_str = models.CharField(max_length=50, help_text="Raw workbook value for ICE Petrol")
    ice_diesel_str = models.CharField(max_length=50, help_text="Raw workbook value for ICE Diesel")
    hev_hybrid_str = models.CharField(max_length=50, help_text="Raw workbook value for HEV Hybrid")
    bev_str = models.CharField(max_length=50, help_text="Raw workbook value for BEV")
    phev_str = models.CharField(max_length=50, help_text="Raw workbook value for PHEV")

    ice_petrol_multiplier = models.FloatField(null=True, blank=True, help_text="Numeric multiplier for ICE Petrol")
    ice_diesel_multiplier = models.FloatField(null=True, blank=True, help_text="Numeric multiplier for ICE Diesel")
    hev_hybrid_multiplier = models.FloatField(null=True, blank=True, help_text="Numeric multiplier for HEV Hybrid")
    bev_multiplier = models.FloatField(null=True, blank=True, help_text="Numeric multiplier for BEV")
    phev_multiplier = models.FloatField(null=True, blank=True, help_text="Numeric multiplier for PHEV")

    rationale = models.TextField(blank=True)
    confidence = models.CharField(max_length=50, blank=True)
    source = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['cost_component']
        verbose_name = 'Energy Type Cost Modifier'
        verbose_name_plural = 'Energy Type Cost Modifiers'

    def __str__(self):
        return f"{self.cost_component} (BEV: {self.bev_str}, HEV: {self.hev_hybrid_str})"

    @classmethod
    def get_multiplier_for_powertrain(cls, component_name: str, powertrain: str) -> float:
        """
        Helper to look up numeric multiplier for a component and powertrain.
        Powertrain is matched against petrol, diesel, hybrid, bev, phev.
        Falls back to 1.0 if not found or non-numeric.
        """
        row = cls.objects.filter(cost_component__iexact=component_name.strip()).first()
        if not row:
            return 1.0

        pt = powertrain.strip().lower() if powertrain else 'petrol'
        if pt in ['petrol', 'ice_petrol', 'gasoline']:
            return row.ice_petrol_multiplier if row.ice_petrol_multiplier is not None else 1.0
        elif pt in ['diesel', 'ice_diesel']:
            return row.ice_diesel_multiplier if row.ice_diesel_multiplier is not None else 1.0
        elif pt in ['hybrid', 'hev', 'hev_hybrid', 'mild_hybrid']:
            return row.hev_hybrid_multiplier if row.hev_hybrid_multiplier is not None else 1.0
        elif pt in ['bev', 'electric', 'ev']:
            return row.bev_multiplier if row.bev_multiplier is not None else 1.0
        elif pt in ['phev', 'plug-in hybrid']:
            return row.phev_multiplier if row.phev_multiplier is not None else 1.0
        return 1.0


class CategoryAnnualKMBenchmark(models.Model):
    """
    Estimated annual travel distance (km/year) by FCAI vehicle category from Section A (Sheet: AnnualKMByCategory).
    Serves as the authoritative travel distance anchor powering variable running costs (fuel, tyres, servicing, EV levies, CO2).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fcai_category = models.CharField(max_length=100, unique=True, help_text="FCAI vehicle category name")
    est_annual_km = models.IntegerField(help_text="Estimated annual distance driven in km")
    basis_pattern = models.TextField(blank=True, help_text="Typical usage profile and driving pattern")
    abs_anchor = models.CharField(max_length=255, blank=True, help_text="Anchor relative to ABS SMVU averages")
    vs_flat_17k = models.CharField(max_length=50, blank=True, help_text="Percentage variance compared to flat 17,000 km/yr")
    impact_on_coo = models.TextField(blank=True, help_text="Impact on Cost of Ownership (COO)")
    confidence = models.CharField(max_length=50, blank=True)
    source = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fcai_category']
        verbose_name = 'Category Annual KM Benchmark'
        verbose_name_plural = 'Category Annual KM Benchmarks'

    def __str__(self):
        return f"{self.fcai_category}: {self.est_annual_km:,} km/yr ({self.vs_flat_17k})"

    @classmethod
    def get_annual_km_for_category(cls, category: str) -> int:
        """Fetch estimated annual km for category with fallback to 13,300 km."""
        row = cls.objects.filter(fcai_category__iexact=category.strip()).first()
        if row and row.est_annual_km:
            return row.est_annual_km
        return 13300


class StateAnnualKMBenchmark(models.Model):
    """
    State-level annual travel distance variations from Section B (Sheet: AnnualKMByCategory).
    Derived from ABS Survey of Motor Vehicle Use (SMVU) 9208.0 (National avg = 12,100 km).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state = models.CharField(max_length=20, unique=True, help_text="State code (e.g. NSW, VIC, QLD, WA, SA, TAS, NT, ACT)")
    avg_km_per_vehicle = models.IntegerField(help_text="Average annual km per vehicle in state")
    vs_national = models.CharField(max_length=50, blank=True, help_text="Variance vs national average 12,100 km")
    source = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['state']
        verbose_name = 'State Annual KM Benchmark'
        verbose_name_plural = 'State Annual KM Benchmarks'

    def __str__(self):
        return f"{self.state}: {self.avg_km_per_vehicle:,} km/yr ({self.vs_national})"

    @classmethod
    def get_annual_km_for_state(cls, state: str) -> int:
        """Fetch average annual km for state with fallback to 12,100 km."""
        row = cls.objects.filter(state__iexact=state.strip()).first()
        if row and row.avg_km_per_vehicle:
            return row.avg_km_per_vehicle
        return 12100


class COOBenchmarkAudit(models.Model):
    """
    Cost of Ownership (COO) annual baseline benchmarks by FCAI category and state (Sheet: COOBenchmarkAudit).
    Provides the master validation cross-check for ICE petrol baseline running costs (sum of fuel, CTP,
    comprehensive insurance, registration, maintenance, and tyres, excluding finance).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fcai_category = models.CharField(max_length=100, help_text="FCAI vehicle category (e.g. Micro, Small, Medium SUV, Light Bus)")
    usage_profile = models.CharField(max_length=50, blank=True, default='Standard', help_text="e.g. Standard, Commercial (30k km), Private")
    km_per_year_used = models.IntegerField(null=True, blank=True, help_text="Category-specific annual km used in computation")

    nsw_coo_cents = models.IntegerField(help_text="NSW Annual COO baseline in whole cents")
    vic_coo_cents = models.IntegerField(help_text="VIC Annual COO baseline in whole cents")
    qld_coo_cents = models.IntegerField(help_text="QLD Annual COO baseline in whole cents")
    sa_coo_cents = models.IntegerField(help_text="SA Annual COO baseline in whole cents")
    wa_coo_cents = models.IntegerField(help_text="WA Annual COO baseline in whole cents")
    tas_coo_cents = models.IntegerField(help_text="TAS Annual COO baseline in whole cents")
    nt_coo_cents = models.IntegerField(help_text="NT Annual COO baseline in whole cents")
    act_coo_cents = models.IntegerField(help_text="ACT Annual COO baseline in whole cents")

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fcai_category', 'usage_profile']
        verbose_name = 'COO Benchmark Audit'
        verbose_name_plural = 'COO Benchmark Audits'

    def __str__(self):
        return f"{self.fcai_category} ({self.usage_profile}): NSW=${self.nsw_coo_cents/100:.0f}, VIC=${self.vic_coo_cents/100:.0f} ({self.km_per_year_used} km)"

    def get_coo_for_state(self, state: str) -> int:
        clean_state = state.strip().upper() if state else 'NSW'
        mapping = {
            'NSW': self.nsw_coo_cents,
            'VIC': self.vic_coo_cents,
            'QLD': self.qld_coo_cents,
            'SA': self.sa_coo_cents,
            'WA': self.wa_coo_cents,
            'TAS': self.tas_coo_cents,
            'NT': self.nt_coo_cents,
            'ACT': self.act_coo_cents,
        }
        return mapping.get(clean_state, self.nsw_coo_cents)

    @classmethod
    def get_benchmark(cls, category: str, state: str) -> int:
        """Fetch baseline COO in cents for category and state with fallback to Medium."""
        row = cls.objects.filter(fcai_category__iexact=category.strip()).first()
        if not row:
            row = cls.objects.filter(fcai_category__iexact='Medium').first()
        if row:
            return row.get_coo_for_state(state)
        return 538000


class VehicleCOOComponentBreakdown(models.Model):
    """
    Granular vehicle-level Cost of Ownership (COO) component breakdown by state from Sheet 21 (COO_Component_Breakdown).
    Itemizes fuel, electricity, CTP, comprehensive insurance, registration, maintenance, tyres, and EV levies.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(
        'Vehicle',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='coo_breakdowns',
        help_text="Optional link to canonical Vehicle record"
    )

    make = models.CharField(max_length=255, db_index=True)
    model = models.CharField(max_length=255, db_index=True)
    variant = models.CharField(max_length=255)
    year = models.IntegerField(db_index=True)
    state = models.CharField(max_length=20, db_index=True)

    fcai_category = models.CharField(max_length=100)
    fcai_broad = models.CharField(max_length=100, blank=True)
    energy_norm = models.CharField(max_length=50, blank=True)
    km_pa_used = models.IntegerField(default=13300)

    fuel_cost_pa_cents = models.IntegerField(default=0)
    electricity_cost_pa_cents = models.IntegerField(default=0)
    ctp_pa_cents = models.IntegerField(default=0)
    comprehensive_pa_cents = models.IntegerField(default=0)
    registration_pa_cents = models.IntegerField(default=0)
    maintenance_pa_cents = models.IntegerField(default=0)
    tyre_cost_pa_cents = models.IntegerField(default=0)
    ev_levy_pa_cents = models.IntegerField(default=0)
    components_sum_pa_cents = models.IntegerField(default=0)
    base_coo_pa_canonical_cents = models.IntegerField(default=0)
    delta_components_vs_canonical_cents = models.IntegerField(default=0)

    scaling_factor_to_canonical = models.FloatField(null=True, blank=True)
    scoring_version = models.CharField(max_length=50, default='v6.3.4-cat-norm')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['make', 'model', 'year', 'variant', 'state']
        indexes = [
            models.Index(fields=['make', 'model', 'year', 'state']),
            models.Index(fields=['fcai_category', 'state']),
        ]
        verbose_name = 'Vehicle COO Component Breakdown'
        verbose_name_plural = 'Vehicle COO Component Breakdowns'

    def __str__(self):
        return f"{self.make} {self.model} {self.variant} ({self.year}) [{self.state}]: ${self.components_sum_pa_cents/100:.2f} p.a."

    @classmethod
    def get_breakdown_for_vehicle(cls, make: str, model: str, variant: str, year: int, state: str):
        return cls.objects.filter(
            make__iexact=make.strip(),
            model__iexact=model.strip(),
            variant__iexact=variant.strip(),
            year=year,
            state__iexact=state.strip(),
        ).first()


class NGAEmissionFactor(models.Model):
    """
    National Greenhouse Accounts (NGA) Scope-2 electricity emission factors from Sheet 23 (NGA_EmissionFactors).
    Powers state-level upstream emissions calculations for Battery Electric Vehicles (BEVs) and Plug-in Hybrids (PHEVs).
    Published by the Department of Climate Change, Energy, the Environment and Water (DCCEEW).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grid = models.CharField(max_length=50, unique=True, help_text="Grid identifier (e.g. NSW/ACT, VIC, QLD, SA, WA-SWIS, TAS, NT-DKIS, National)")
    states_covered = models.CharField(max_length=100, help_text="Jurisdiction or state code covered (e.g. NSW, ACT, VIC, Australia)")
    scope2_factor_kgco2e_per_kwh = models.FloatField(help_text="Scope 2 emission factor in kg CO2-e per kWh (e.g. 0.64, 0.78, 0.20)")
    edition = models.CharField(max_length=100, blank=True, help_text="e.g. NGA Factors 2025 (DCCEEW)")
    effective_period = models.CharField(max_length=100, blank=True, help_text="e.g. FY2025-26 (current to ~Aug 2026)")
    source = models.CharField(max_length=255, blank=True)
    devspec_ref = models.CharField(max_length=100, blank=True, help_text="e.g. Calc §2.10 Emissions; §8 Dataset")
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['grid']
        verbose_name = 'NGA Emission Factor'
        verbose_name_plural = 'NGA Emission Factors'

    def __str__(self):
        return f"{self.grid} ({self.states_covered}): {self.scope2_factor_kgco2e_per_kwh} kg CO2e/kWh"

    @classmethod
    def get_factor_for_state(cls, state: str) -> float:
        """
        Lookup Scope-2 emission factor for state (e.g. 'NSW', 'VIC', 'TAS', 'SA', 'WA', 'QLD', 'NT', 'ACT').
        Falls back to National factor (0.62) if state is unknown.
        """
        clean_state = state.strip().upper() if state else 'NATIONAL'
        state_map = {
            'NSW': 'NSW/ACT',
            'ACT': 'NSW/ACT',
            'VIC': 'VIC',
            'QLD': 'QLD',
            'SA': 'SA',
            'WA': 'WA-SWIS',
            'TAS': 'TAS',
            'NT': 'NT-DKIS',
            'NATIONAL': 'National',
        }
        grid_key = state_map.get(clean_state, clean_state)
        row = cls.objects.filter(grid__iexact=grid_key).first()
        if not row:
            row = cls.objects.filter(states_covered__icontains=clean_state).first()
        if not row:
            row = cls.objects.filter(grid__iexact='National').first()
        if row and row.scope2_factor_kgco2e_per_kwh:
            return row.scope2_factor_kgco2e_per_kwh
        return 0.62


class DriveawayTaxParameter(models.Model):
    """
    Tax, duty, excise, and government incentive parameters from Sheet 24 (DriveawayTaxParameters).
    Powers Australian Luxury Car Tax (LCT), state stamp duty schedules, fuel excise, and EV rebate calculations.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parameter = models.CharField(max_length=255, unique=True, help_text="e.g. LCT threshold — fuel-efficient, VIC EV cash subsidy")
    value = models.CharField(max_length=255, help_text="Configured value, status, or formula rule")
    effective_from = models.CharField(max_length=100, blank=True, help_text="e.g. 2026-07-01, ongoing, to 2027-06-30")
    applies_to = models.CharField(max_length=255, blank=True, help_text="Target vehicle scope or jurisdiction")
    source = models.CharField(max_length=255, blank=True, help_text="Statutory authority or revenue office")
    devspec_ref = models.CharField(max_length=100, blank=True, help_text="e.g. Calc §2.1, Calc §2.3, Calc §2.9")
    note = models.TextField(blank=True, help_text="Policy nuances, sunset clauses, or income caps")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['parameter']
        verbose_name = 'Driveaway Tax Parameter'
        verbose_name_plural = 'Driveaway Tax Parameters'

    def __str__(self):
        return f"{self.parameter}: {self.value} ({self.applies_to})"

    @classmethod
    def get_param(cls, name: str):
        return cls.objects.filter(parameter__iexact=name.strip()).first()













