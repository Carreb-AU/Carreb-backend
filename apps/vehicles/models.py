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


class GreenVehicleGuideRecord(models.Model):
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
    transmission = models.CharField(max_length=100, blank=True)

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
            GinIndex(fields=['search_text'], name='gvg_search_trgm_idx', opclasses=['gin_trgm_ops']),
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
    
    ancap_safety_rating = models.IntegerField(null=True, blank=True)
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
    scoring_version = models.CharField(max_length=50, blank=True)
    
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
