import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from rest_framework.test import APIClient

client = APIClient()

res = client.post('/api/core-rating/search/', {
    "target_band_slug": "steady-cruiser",
    "state": "NSW",
    "priority_slider": 3,
    "core_mode": "pure_cost",
    "budget_min": 1000000,
    "budget_max": 9000000
}, format='json')

print(res.status_code)
print(res.json().get('meta', {}).get('total_matches'))
