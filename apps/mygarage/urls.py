from django.urls import path
from apps.mygarage.views import (
    CurrentVehicleView,
    CurrentVehicleSearchView,
    CurrentVehicleDetailsView,
    CurrentVehicleOverrideDeleteView,
    CurrentVehicleAutoFillView,
    GarageVehicleListView,
    GarageVehicleDetailView,
    GarageVehicleOverrideView,
    GarageVehicleArchiveView,
    GarageVehicleUnarchiveView,
    GarageVehicleDeleteView,
    ArchiveListView,
    PriorityStateView,
    CoreDialBandBreakdownView,
    SavingsSummaryView,
    SpotlightsView
)

urlpatterns = [
    # Current Vehicle
    path('api/my-garage/current-vehicle/', CurrentVehicleView.as_view(), name='current-vehicle'),
    path('api/my-garage/current-vehicle/search/', CurrentVehicleSearchView.as_view(), name='current-vehicle-search'),
    path('api/my-garage/current-vehicle/details/', CurrentVehicleDetailsView.as_view(), name='current-vehicle-details'),
    path('api/my-garage/current-vehicle/override/<str:field_name>/', CurrentVehicleOverrideDeleteView.as_view(), name='current-vehicle-override-delete'),
    path('api/my-garage/current-vehicle/auto-fill/', CurrentVehicleAutoFillView.as_view(), name='current-vehicle-auto-fill'),
    
    # Garage Vehicles
    path('api/my-garage/vehicles/', GarageVehicleListView.as_view(), name='garage-vehicles'),
    path('api/my-garage/vehicles/<uuid:garage_vehicle_id>/', GarageVehicleDetailView.as_view(), name='garage-vehicle-detail'),
    path('api/my-garage/vehicles/<uuid:garage_vehicle_id>/details/', GarageVehicleOverrideView.as_view(), name='garage-vehicle-details-override'),
    path('api/my-garage/vehicles/<uuid:garage_vehicle_id>/override/<str:field_name>/', GarageVehicleOverrideView.as_view(), name='garage-vehicle-override-delete'),
    path('api/my-garage/vehicles/<uuid:garage_vehicle_id>/archive/', GarageVehicleArchiveView.as_view(), name='garage-vehicle-archive'),
    path('api/my-garage/vehicles/<uuid:garage_vehicle_id>/unarchive/', GarageVehicleUnarchiveView.as_view(), name='garage-vehicle-unarchive'),
    path('api/my-garage/vehicles/<uuid:garage_vehicle_id>/delete/', GarageVehicleDeleteView.as_view(), name='garage-vehicle-delete'),
    
    # Archive
    path('api/my-garage/archive/', ArchiveListView.as_view(), name='garage-archive-list'),
    
    # Priority State & Dial
    path('api/my-garage/priority-state/', PriorityStateView.as_view(), name='priority-state'),
    path('api/my-garage/core-dial/band-breakdown/<slug:band_slug>/', CoreDialBandBreakdownView.as_view(), name='core-dial-band-breakdown'),
    
    # Savings & Spotlights
    path('api/my-garage/savings-summary/', SavingsSummaryView.as_view(), name='savings-summary'),
    path('api/my-garage/spotlights/', SpotlightsView.as_view(), name='spotlights'),
]
