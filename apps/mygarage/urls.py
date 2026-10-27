from django.urls import path
from apps.mygarage.views import (
    CurrentVehicleView,
    CurrentVehicleSearchView,
    CurrentVehicleDetailsView,
    CurrentVehicleOverrideDeleteView,
    CurrentVehicleAutoFillView,
    CurrentVehicleSuggestionsView,
    AIVehicleSearchView,
    GarageVehicleListView,
    GarageVehicleDetailView,
    GarageVehicleOverrideView,
    GarageVehicleArchiveView,
    GarageVehicleUnarchiveView,
    GarageVehicleDeleteView,
    ArchiveListView,
    PriorityStateView,
    SavingsSummaryView,
    SpotlightsView,
    AISmartMatchView,
    RideRevealCreditsView,
    RideRevealGenerateView,
    RideRevealJobView,
    RideRevealResultView,
    RideRevealPurchaseView,
    StripeWebhookView
)
from apps.mygarage.find_dealer_views import FindDealerView, DealerLinkClickedAnalyticsView

urlpatterns = [
    # Find Dealer
    path('api/my-garage/find-dealer/', FindDealerView.as_view(), name='find-dealer'),
    path('api/analytics/dealer-link-clicked/', DealerLinkClickedAnalyticsView.as_view(), name='dealer-link-clicked'),

    # Current Vehicle
    path('api/my-garage/current-vehicle/', CurrentVehicleView.as_view(), name='current-vehicle'),
    path('api/my-garage/current-vehicle/search/', CurrentVehicleSearchView.as_view(), name='current-vehicle-search'),
    path('api/my-garage/current-vehicle/details/', CurrentVehicleDetailsView.as_view(), name='current-vehicle-details'),
    path('api/my-garage/current-vehicle/override/<str:field_name>/', CurrentVehicleOverrideDeleteView.as_view(), name='current-vehicle-override-delete'),
    path('api/my-garage/current-vehicle/auto-fill/', CurrentVehicleAutoFillView.as_view(), name='current-vehicle-auto-fill'),
    path('api/current-vehicle/suggestions/', CurrentVehicleSuggestionsView.as_view(), name='current-vehicle-suggestions'),
    path('api/current-vehicle/makes/', CurrentVehicleSuggestionsView.as_view(), name='current-vehicle-makes'),
    path('api/current-vehicle/models/', CurrentVehicleSuggestionsView.as_view(), name='current-vehicle-models'),
    path('api/current-vehicle/years/', CurrentVehicleSuggestionsView.as_view(), name='current-vehicle-years'),
    path('api/current-vehicle/ai-search/', AIVehicleSearchView.as_view(), name='current-vehicle-ai-search'),
    
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
    
    # Savings & Spotlights
    path('api/my-garage/savings-summary/', SavingsSummaryView.as_view(), name='savings-summary'),
    path('api/my-garage/spotlights/', SpotlightsView.as_view(), name='spotlights'),
    
    # AI Smart Match
    path('api/my-garage/ai-smart-match/', AISmartMatchView.as_view(), name='ai-smart-match'),
    
    # RideReveal
    path('api/my-garage/ridereveal/credits/', RideRevealCreditsView.as_view(), name='ridereveal-credits'),
    path('api/my-garage/ridereveal/generate/', RideRevealGenerateView.as_view(), name='ridereveal-generate'),
    path('api/my-garage/ridereveal/job/<uuid:job_id>/', RideRevealJobView.as_view(), name='ridereveal-job'),
    path('api/my-garage/ridereveal/result/<uuid:garage_vehicle_id>/', RideRevealResultView.as_view(), name='ridereveal-result'),
    path('api/my-garage/ridereveal/purchase/', RideRevealPurchaseView.as_view(), name='ridereveal-purchase'),
    
    # Stripe Webhook
    path('api/stripe/webhook/ridereveal-purchase/', StripeWebhookView.as_view(), name='stripe-webhook-ridereveal-purchase'),
]
