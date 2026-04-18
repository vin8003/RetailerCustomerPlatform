import pytest
from django.urls import reverse
from rest_framework import status
from unittest.mock import patch
from .factories import UserFactory
from authentication.models import User, OTPVerification, EmailOTPVerification
from fcm_django.models import FCMDevice
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta

_original_cache_get = cache.get

def _mock_cache_get(key, default=None):
    if str(key).startswith("resend_otp_limit_") or str(key).startswith("otp_requests_") or str(key).startswith("resend_email_otp_"):
        return 3
    return _original_cache_get(key, default)

@pytest.mark.django_db
class TestAuthViewsExtended:
    
    @patch('authentication.views.send_sms_otp')
    def test_request_phone_verification(self, mock_send, api_client):
        # Setup
        cache.clear()
        mock_send.return_value = True
        user = UserFactory(username="phonev", phone_number="", is_phone_verified=False)
        api_client.force_authenticate(user=user)
        
        url = reverse('request_phone_verification')
        
        # Missing phone
        res1 = api_client.post(url)
        assert res1.status_code == status.HTTP_400_BAD_REQUEST
        
        # Already verified
        user.phone_number = "+911111111111"
        user.is_phone_verified = True
        user.save()
        res2 = api_client.post(url)
        assert res2.status_code == status.HTTP_200_OK
        
        # Success
        user.is_phone_verified = False
        user.save()
        res3 = api_client.post(url)
        assert res3.status_code == status.HTTP_200_OK
        # Rate Limiting (3 attempts max)
        with patch('authentication.views.cache.get', side_effect=_mock_cache_get):
            res_limit = api_client.post(url)
            assert res_limit.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        
        # Exception to cover 500 block
        with patch('authentication.views.generate_otp', side_effect=Exception("Crash")):
            res4 = api_client.post(url)
            assert res4.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @patch('authentication.views.send_sms_otp')
    def test_resend_otp(self, mock_send, api_client):
        cache.clear()
        mock_send.return_value = True
        url = reverse('resend_otp')
        
        # Invalid Phone
        res1 = api_client.post(url, {"phone_number": "+1234"})
        assert res1.status_code == status.HTTP_400_BAD_REQUEST 
        
        # Not found
        res2 = api_client.post(url, {"phone_number": "+918888888888"})
        assert res2.status_code == status.HTTP_404_NOT_FOUND
        
        # Success
        user = User.objects.create_user(username="resendUser", phone_number="+918888888888", user_type='customer')
        res3 = api_client.post(url, {"phone_number": "+918888888888"})
        assert res3.status_code == status.HTTP_200_OK
        
        # Limits
        with patch('authentication.views.cache.get', side_effect=_mock_cache_get):
            res4 = api_client.post(url, {"phone_number": "+918888888888"})
            assert res4.status_code == status.HTTP_429_TOO_MANY_REQUESTS

        # Exception to cover 500
        with patch('authentication.views.generate_otp', side_effect=Exception("Crash")):
            res5 = api_client.post(url, {"phone_number": "+918888888888"})
            assert res5.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_register_device(self, api_client):
        url = reverse('register_device')
        
        # Unauthorized
        res1 = api_client.post(url, {"registration_id": "token123"})
        assert res1.status_code == status.HTTP_401_UNAUTHORIZED
        
        user = UserFactory(username="devuser")
        api_client.force_authenticate(user=user)
        
        # Missing token
        res2 = api_client.post(url)
        assert res2.status_code == status.HTTP_400_BAD_REQUEST
        
        # Success
        res3 = api_client.post(url, {"registration_id": "token123"})
        assert res3.status_code == status.HTTP_200_OK
        
        # Update existing
        res4 = api_client.post(url, {"registration_id": "token123", "name": "newdev"})
        assert res4.status_code == status.HTTP_200_OK
        
        # Check DB
        assert FCMDevice.objects.get(registration_id="token123").name == "newdev"

    @patch('authentication.views.send_email_otp')
    def test_verify_and_resend_email_otp(self, mock_send, api_client):
        cache.clear()
        mock_send.return_value = True
        
        url_verify = reverse('verify_email_otp')
        url_resend = reverse('resend_email_otp')
        
        user = User.objects.create_user(username="emv", email="emv@test.com")
        
        # Verify Missing
        res1 = api_client.post(url_verify, {"email": "emv@test.com", "otp_code": "123456"})
        assert res1.status_code == status.HTTP_400_BAD_REQUEST
        
        # Create OTP
        otp_obj = EmailOTPVerification.objects.create(
            user=user, email="emv@test.com", otp_code="123456",
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        
        # Verify Wrong OTP
        res2 = api_client.post(url_verify, {"email": "emv@test.com", "otp_code": "000000"})
        assert res2.status_code == status.HTTP_400_BAD_REQUEST
        
        # Verify Expired
        otp_obj.expires_at = timezone.now() - timedelta(minutes=5)
        otp_obj.save()
        res3 = api_client.post(url_verify, {"email": "emv@test.com", "otp_code": "123456"})
        assert res3.status_code == status.HTTP_400_BAD_REQUEST
        
        # Verify Success
        otp_obj.expires_at = timezone.now() + timedelta(minutes=5)
        otp_obj.save()
        res4 = api_client.post(url_verify, {"email": "emv@test.com", "otp_code": "123456"})
        assert res4.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.is_email_verified is True
        
        # Resend Validation Fail
        res5 = api_client.post(url_resend, {"email": "missing@test.com"})
        assert res5.status_code == status.HTTP_400_BAD_REQUEST
        
        # Resend Success
        res6 = api_client.post(url_resend, {"email": "emv@test.com"})
        assert res6.status_code == status.HTTP_200_OK
        
        # Resend Limits
        with patch('authentication.views.cache.get', side_effect=_mock_cache_get):
            res7 = api_client.post(url_resend, {"email": "emv@test.com"})
            assert res7.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        
        # 500 Server Error
        with patch('authentication.views.generate_otp', side_effect=Exception("Crash")):
            res8 = api_client.post(url_resend, {"email": "emv@test.com"})
            assert res8.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
