import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.cache import cache

User = get_user_model()

@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def user():
    return User.objects.create_user(email='test@example.com', password='password123', first_name='Test', last_name='User')

@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()

@pytest.mark.django_db
class TestSupportAPI:
    def test_contact_us_success(self, api_client):
        url = reverse('contact_us')
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "topic": "Customer Inquiry",
            "what_describes_you": "Customer Inquiry",
            "message": "I need help with my account."
        }
        response = api_client.post(url, data, format='json', REMOTE_ADDR='127.0.0.1')
        assert response.status_code == 200
        assert response.data['submitted'] is True

    def test_contact_us_invalid_topic(self, api_client):
        url = reverse('contact_us')
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "topic": "Invalid Topic",
            "what_describes_you": "Customer Inquiry",
            "message": "Test message"
        }
        response = api_client.post(url, data, format='json')
        assert response.status_code == 422
        # Check error format
        errors = response.data
        assert any(e['field'] == 'topic' for e in errors)

    def test_contact_us_rate_limit(self, api_client):
        url = reverse('contact_us')
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "topic": "Customer Inquiry",
            "what_describes_you": "Customer Inquiry",
            "message": "Rate limit test"
        }
        # Send 3 requests (limit is 3)
        for _ in range(3):
            response = api_client.post(url, data, format='json', REMOTE_ADDR='192.168.1.1')
            assert response.status_code == 200

        # 4th request should fail
        response = api_client.post(url, data, format='json', REMOTE_ADDR='192.168.1.1')
        assert response.status_code == 429
        assert response.data['error'] == 'rate_limit_exceeded'

    def test_get_in_touch_auth_required(self, api_client):
        url = reverse('get_in_touch')
        response = api_client.post(url, {}, format='json')
        assert response.status_code == 401

    def test_get_in_touch_success(self, api_client, user):
        api_client.force_authenticate(user=user)
        url = reverse('get_in_touch')
        data = {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@example.com",
            "topic": "Customer Inquiry",
            "what_describes_you": "Customer Inquiry",
            "message": "Auth message"
        }
        response = api_client.post(url, data, format='json')
        assert response.status_code == 200

    def test_prefill(self, api_client, user):
        api_client.force_authenticate(user=user)
        url = reverse('prefill')
        response = api_client.get(url)
        assert response.status_code == 200
        assert response.data['first_name'] == 'Test'
        assert response.data['last_name'] == 'User'
        assert response.data['email'] == 'test@example.com'
