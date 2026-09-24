from django.urls import path
from apps.vehicles.views import (
    VehicleListView,
    VehicleDetailView,
    VehicleJsonLdView,
    VehicleBrandsView,
    VehicleModelsView,
    VehicleYearsView,
    VehicleVariantsView,
    CoreRatingCalculateView,
    CoreRatingBatchView,
    CoreSearchView,
    VehicleDataUploadView
)
from apps.vehicles.calculator_lookup_api import VehicleCalculatorLookupAPIView
from apps.vehicles.cost_estimator_api import VehicleCostEstimatorAPIView

urlpatterns = [
    path('api/vehicles/', VehicleListView.as_view(), name='vehicle-list'),
    path('api/vehicles/brands/', VehicleBrandsView.as_view(), name='vehicle-brands'),
    path('api/vehicles/models/', VehicleModelsView.as_view(), name='vehicle-models'),
    path('api/vehicles/years/', VehicleYearsView.as_view(), name='vehicle-years'),
    path('api/vehicles/variants/', VehicleVariantsView.as_view(), name='vehicle-variants'),
    
    path('api/vehicles/<uuid:vehicle_id>/', VehicleDetailView.as_view(), name='vehicle-detail'),
    path('api/vehicles/<uuid:vehicle_id>/json-ld/', VehicleJsonLdView.as_view(), name='vehicle-json-ld'),
    
    path('api/core-rating/calculate/', CoreRatingCalculateView.as_view(), name='core-rating-calculate'),
    path('api/core-rating/batch/', CoreRatingBatchView.as_view(), name='core-rating-batch'),
    path('api/core-rating/search/', CoreSearchView.as_view(), name='core-rating-search'),
    
    path('api/vehicles/upload/', VehicleDataUploadView.as_view(), name='vehicle-upload'),
    
    # Read-Only Vehicle Name Lookup & Auto-Fill API for Calculator UI
    path('api/v1/vehicles/lookup/', VehicleCalculatorLookupAPIView.as_view(), name='vehicle-calculator-lookup-v1'),
    path('api/vehicles/lookup/', VehicleCalculatorLookupAPIView.as_view(), name='vehicle-calculator-lookup'),

    # Interactive Vehicle Cost Estimator API ("What Could Your Car Be Costing You to Run?")
    path('api/v1/vehicles/estimate-cost/', VehicleCostEstimatorAPIView.as_view(), name='vehicle-cost-estimator-v1'),
    path('api/vehicles/estimate-cost/', VehicleCostEstimatorAPIView.as_view(), name='vehicle-cost-estimator'),
]

