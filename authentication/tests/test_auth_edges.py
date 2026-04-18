import pytest
from unittest.mock import patch, MagicMock
from django.urls import reverse
from rest_framework import status
from django.conf import settings

@pytest.mark.django_db
class TestAuthViewEdges:
    
    def test_retailer_signup_invalid_serializer(self, api_client):
        # Trigger line 92: return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        url = reverse('retailer_signup')
        data = {
            'access_code': settings.RETAILER_ACCESS_CODE,
            'username': '', # Invalid
        }
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_retailer_login_wrong_user_type(self, api_client, customer):
        # Trigger line 116: if user.user_type != 'retailer'
        url = reverse('retailer_login')
        customer.set_password('password')
        customer.save()
        data = {'username': customer.username, 'password': 'password'}
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error'] == 'Invalid user type for retailer login'

    @patch('authentication.views.OTPRequestSerializer.is_valid')
    def test_request_otp_exception(self, mock_is_valid, api_client):
        # Trigger lines 395-401: except Exception as e
        mock_is_valid.side_effect = Exception("OTP error")
        url = reverse('resend_otp')
        response = api_client.post(url, {})
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @patch('authentication.views.EmailVerifySerializer.is_valid')
    def test_verify_email_otp_exception(self, mock_is_valid, api_client):
        # Generic exception test for email verification views
        mock_is_valid.side_effect = Exception("Serializer error")
        url = reverse('verify_email_otp')
        response = api_client.post(url, {'email': 't@t.com', 'otp_code': '123456'})
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
