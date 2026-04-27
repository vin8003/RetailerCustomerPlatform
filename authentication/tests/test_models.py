import pytest
from django.utils import timezone
from authentication.models import User, OTPVerification, UserSession, EmailOTPVerification
from datetime import timedelta
from django.conf import settings

@pytest.mark.django_db
class TestAuthenticationModels:
    def test_user_str(self):
        user = User.objects.create(username='testuser', user_type='customer')
        assert str(user) == "testuser (customer)"

    def test_otp_verification_str(self):
        user = User.objects.create(username='otpuser')
        otp = OTPVerification.objects.create(
            user=user, phone_number='+1234567890', otp_code='123456',
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        assert str(otp) == "OTP for +1234567890"

    def test_user_session_str(self):
        user = User.objects.create(username='sessionuser')
        session = UserSession.objects.create(
            user=user, session_token='token123'
        )
        assert str(session) == "Session for sessionuser"

    def test_email_otp_str(self):
        user = User.objects.create(username='emailuser')
        email_otp = EmailOTPVerification.objects.create(
            user=user, email='test@example.com', otp_code='123456',
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        assert str(email_otp) == "Email OTP for test@example.com"
        
    def test_email_otp_is_expired(self):
        user = User.objects.create(username='emailuserexp')
        # Not expired
        email_otp = EmailOTPVerification.objects.create(
            user=user, email='testexp@example.com', otp_code='123456',
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        assert email_otp.is_expired() is False
        
        # Expired
        email_otp.expires_at = timezone.now() - timedelta(minutes=1)
        email_otp.save()
        assert email_otp.is_expired() is True
        
    def test_email_otp_can_retry(self):
        user = User.objects.create(username='emailuserretry')
        email_otp = EmailOTPVerification.objects.create(
            user=user, email='testretry@example.com', otp_code='123456',
            expires_at=timezone.now() + timedelta(minutes=5),
            attempts=0
        )
        assert email_otp.can_retry() is True
        
        email_otp.attempts = settings.OTP_MAX_ATTEMPTS
        email_otp.save()
        assert email_otp.can_retry() is False
