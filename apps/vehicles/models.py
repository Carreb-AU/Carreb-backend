import uuid
from django.db import models
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

class Vehicle(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    brand = models.CharField(max_length=255)
    model = models.CharField(max_length=255)
    year = models.IntegerField()
    variant = models.CharField(max_length=255)
    body_style = models.CharField(max_length=100)
    num_seats = models.IntegerField()
    powertrain_type = models.CharField(max_length=50, choices=PowertrainType.choices)
    fcai_category = models.CharField(max_length=100)
    ancap_safety_rating = models.IntegerField(null=True, blank=True)
    driveaway_price_by_state = models.JSONField(default=dict)
    
    fuel_consumption_per_100km = models.FloatField(null=True, blank=True)
    electricity_consumption_per_100km = models.FloatField(null=True, blank=True)
    tailpipe_co2_g_per_km = models.FloatField(null=True, blank=True)
    wltp_range_km = models.FloatField(null=True, blank=True)
    test_cycle = models.CharField(max_length=20, choices=TestCycle.choices)
    
    annual_km_default = models.IntegerField()
    insurance_estimate_by_state = models.JSONField(default=dict)
    ctp_by_state = models.JSONField(default=dict)
    registration_by_state = models.JSONField(default=dict)
    servicing_5yr_estimate = models.IntegerField()
    tyre_replacement_estimate = models.IntegerField()
    resale_value_5yr_estimate = models.IntegerField()
    
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
