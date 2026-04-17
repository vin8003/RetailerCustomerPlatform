import pytest
from django.urls import reverse
from rest_framework import status
from django.conf import settings
from .factories import UserFactory, RetailerUserFactory
from authentication.models import User, EmailOTPVerification

@pytest.mark.django_db
class TestAuthFlows:
    
    def test_retailer_signup_success(self, api_client, mock_email_send):
        url = reverse('retailer_signup')
        payload = {
            "username": "new_retailer",
            "email": "retailer@example.com",
            "password": "StrongPassword123!",
            "password_confirm": "StrongPassword123!",
            "phone_number": "+919999988888",
            "access_code": settings.RETAILER_ACCESS_CODE
        }
        response = api_client.post(url, payload, format='json')
        
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data['message'] == 'Retailer registered successfully'
        assert User.objects.filter(username="new_retailer", user_type='retailer').exists()
        # Verify retailer profile was created
        user = User.objects.get(username="new_retailer")
        assert hasattr(user, 'retailer_profile')

    def test_retailer_signup_invalid_access_code(self, api_client):
        url = reverse('retailer_signup')
        payload = {
            "username": "fake_retailer",
            "password": "StrongPassword123!",
            "password_confirm": "StrongPassword123!",
            "access_code": "WRONG_CODE"
        }
        response = api_client.post(url, payload)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error'] == 'Invalid Access Code'

    def test_customer_signup_success(self, api_client, mock_email_send):
        url = reverse('customer_signup')
        payload = {
            "username": "test_customer",
            "email": "customer@example.com",
            "password": "StrongPassword123!",
            "password_confirm": "StrongPassword123!",
            "phone_number": "+918888877777"
        }
        response = api_client.post(url, payload)
        
        assert response.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(username="test_customer", user_type='customer').exists()
        # Verify Email OTP was created
        assert EmailOTPVerification.objects.filter(email="customer@example.com").exists()
        # Verify email was "sent" (mock called)
        assert mock_email_send.called

    def test_customer_login_success(self, api_client):
        # Create a verified customer
        user = UserFactory(username="login_user", is_email_verified=True)
        user.set_password("mypassword")
        user.save()
        
        url = reverse('customer_login')
        payload = {
            "username": "login_user",
            "password": "mypassword"
        }
        response = api_client.post(url, payload)
        
        assert response.status_code == status.HTTP_200_OK
        assert 'tokens' in response.data
        assert response.data['user']['username'] == "login_user"

    def test_customer_login_unverified_email(self, api_client):
        user = UserFactory(username="unverified_user", is_email_verified=False)
        user.set_password("mypassword")
        user.save()
        
        url = reverse('customer_login')
        payload = {
            "username": "unverified_user",
            "password": "mypassword"
        }
        response = api_client.post(url, payload)
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data['code'] == 'email_not_verified'
