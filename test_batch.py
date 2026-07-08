import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.vehicles.models import Vehicle
from apps.vehicles.services.rating_engine import calculate_core_rating

v1 = Vehicle.objects.first()
v2 = Vehicle.objects.last()

print(v1.id, v2.id)

from rest_framework.test import APIClient
from apps.users.models import User

client = APIClient()
user = User.objects.create(email="test_batch@example.com", email_verified=True)
client.force_authenticate(user=user)

res = client.post('/api/core-rating/batch/', {
    "vehicle_ids": [str(v1.id), str(v2.id)],
    "state": "NSW",
    "priority_slider": 3,
    "core_mode": "pure_cost"
}, format='json')

print(res.status_code)
print(res.json())
