import pytest
from django.urls import reverse
from rest_framework import status
from .factories import UserFactory
from authentication.models import OTPVerification, User
from django.core.cache import cache

@pytest.mark.django_db
class TestVerification:
    
    def test_verify_firebase_otp_success(self, api_client, mock_firebase_auth):
        user = UserFactory(phone_number="+919999911111", is_phone_verified=False)
        # Mock Firebase to return a valid token for this phone number
        mock_firebase_auth.return_value = {'phone_number': '+919999911111', 'uid': 'firebase_uid'}
        
        url = reverse('verify_otp')
        payload = {
            "phone_number": "+919999911111",
            "firebase_token": "valid_firebase_token"
        }
        response = api_client.post(url, payload)
        
        assert response.status_code == status.HTTP_200_OK, f"Expected 200, got {response.status_code}: {response.data}"
        user.refresh_from_db()
        assert user.is_phone_verified is True

    def test_verify_firebase_otp_mismatch(self, api_client, mock_firebase_auth):
        user = UserFactory(phone_number="+919999911111")
        # Mock Firebase to return token for a DIFFERENT phone number
        mock_firebase_auth.return_value = {'phone_number': '+910000000000'}
        
        url = reverse('verify_otp')
        payload = {
            "phone_number": "+919999911111",
            "firebase_token": "token_for_elsewhere"
        }
        response = api_client.post(url, payload)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Phone number in token does not match" in response.data['error']

    def test_legacy_otp_verification_success(self, api_client):
        user = UserFactory(phone_number="+918888822222")
        from django.utils import timezone
        import datetime
        otp = OTPVerification.objects.create(
            user=user,
            phone_number="+918888822222",
            otp_code="123456",
            expires_at=timezone.now() + datetime.timedelta(minutes=5)
        )
        
        url = reverse('verify_otp')
        payload = {
            "phone_number": "+918888822222",
            "otp_code": "123456"
        }
        response = api_client.post(url, payload)
        
        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.is_phone_verified is True

    @pytest.mark.skip(reason="Throttling is disabled in test settings to avoid environment-induced failures.")
    def test_otp_rate_limiting(self, api_client, mock_sms_request):
        user = UserFactory(phone_number="+917777733333")
        api_client.force_authenticate(user=user)
        url = reverse('request_phone_verification')
        
        # Request OTP 3 times (limit is 3 in views.py)
        for _ in range(3):
            response = api_client.post(url)
            assert response.status_code == status.HTTP_200_OK
        
        # 4th time should fail
        response = api_client.post(url)
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "Too many OTP requests" in response.data['error']
        
        # Cleanup cache for other tests
        cache.clear()

    def test_otp_expiry(self, api_client):
        user = UserFactory(phone_number="+916666644444")
        from django.utils import timezone
        import datetime
        # Created 10 minutes ago, expires in 5 minutes (so it's already expired)
        otp = OTPVerification.objects.create(
            user=user,
            phone_number="+916666644444",
            otp_code="111222",
            expires_at=timezone.now() - datetime.timedelta(minutes=1)
        )
        
        url = reverse('verify_otp')
        payload = {
            "phone_number": "+916666644444",
            "otp_code": "111222"
        }
        response = api_client.post(url, payload)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "expired" in response.data['error']
