from django.urls import path
from apps.vehicles.views import (
    VehicleListView,
    VehicleDetailView,
    VehicleBrandsView,
    VehicleModelsView,
    VehicleYearsView,
    VehicleVariantsView,
    CoreRatingCalculateView,
    CoreRatingBatchView,
    VehicleDataUploadView
)

urlpatterns = [
    path('api/vehicles/', VehicleListView.as_view(), name='vehicle-list'),
    path('api/vehicles/brands/', VehicleBrandsView.as_view(), name='vehicle-brands'),
    path('api/vehicles/models/', VehicleModelsView.as_view(), name='vehicle-models'),
    path('api/vehicles/years/', VehicleYearsView.as_view(), name='vehicle-years'),
    path('api/vehicles/variants/', VehicleVariantsView.as_view(), name='vehicle-variants'),
    
    path('api/vehicles/<uuid:vehicle_id>/', VehicleDetailView.as_view(), name='vehicle-detail'),
    
    path('api/core-rating/calculate/', CoreRatingCalculateView.as_view(), name='core-rating-calculate'),
    path('api/core-rating/batch/', CoreRatingBatchView.as_view(), name='core-rating-batch'),
    
    path('api/vehicles/upload/', VehicleDataUploadView.as_view(), name='vehicle-upload'),
]
