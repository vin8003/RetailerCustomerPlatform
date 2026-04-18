import pytest
from django.urls import reverse
from rest_framework import status
from authentication.models import User, OTPVerification, EmailOTPVerification
from retailers.models import RetailerProfile
from unittest.mock import patch

@pytest.mark.django_db
class TestAuthenticationPhase3:

    def test_retailer_signup_flow(self, api_client):
        # Trigger retailer_signup (Lines 40-91)
        url = reverse('retailer_signup')
        data = {
            'username': 'new_retailer_p3',
            'password': 'Password@123',
            'password_confirm': 'Password@123',
            'email': 'retailer_p3@example.com',
            'phone_number': '+911234567890',
            'first_name': 'Shop',
            'last_name': 'Owner',
        }
        
        # 2. Success with Mocked settings
        with patch('django.conf.settings.RETAILER_ACCESS_CODE', 'TEST_CODE'):
            valid_data = data.copy()
            valid_data['access_code'] = 'TEST_CODE'
            response = api_client.post(url, valid_data, format='json')
            if response.status_code != 201:
                pytest.fail(f"Retailer Signup Error: {response.data}")
            assert response.status_code == status.HTTP_201_CREATED
            assert 'tokens' in response.data
            assert RetailerProfile.objects.filter(user__username='new_retailer_p3').exists()

    def test_customer_signup_with_stale_account(self, api_client, mock_email_send):
        # Trigger customer_signup logic (Lines 148-216, including purging at 165)
        url = reverse('customer_signup')
        stale_username = 'stale_user'
        
        # Create a stale unverified account
        stale_user = User.objects.create_user(
            username=stale_username, 
            password='oldpassword', 
            user_type='customer'
        )
        stale_user.is_email_verified = False
        stale_user.save()
        
        # Signup again with same username
        data = {
            'username': stale_username,
            'password': 'NewPassword@123',
            'password_confirm': 'NewPassword@123',
            'email': 'stale@example.com',
            'phone_number': '+919998887776'
        }
        
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        
        # Verify stale account was purged and new one created
        new_user = User.objects.get(username=stale_username)
        assert new_user.id != stale_user.id
        assert EmailOTPVerification.objects.filter(user=new_user).exists()

    def test_retailer_customer_login_mismatch(self, api_client):
        # Trigger retailer_login and customer_login branches (Lines 114, 243)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        retailer_user = User.objects.create_user(username='ret1', password='pass', user_type='retailer')
        customer_user = User.objects.create_user(username='cust1', password='pass', user_type='customer')
        customer_user.is_email_verified = True
        customer_user.save()
        
        # 1. Retailer login with customer credentials
        url_ret = reverse('retailer_login')
        response = api_client.post(url_ret, {'username': 'cust1', 'password': 'pass'})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        
        # 2. Customer login with retailer credentials
        url_cust = reverse('customer_login')
        response = api_client.post(url_cust, {'username': 'ret1', 'password': 'pass'})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_customer_login_unverified_block(self, api_client):
        # Trigger line 250 in authentication/views.py
        user = User.objects.create_user(username='unverified', password='pass', user_type='customer')
        user.is_email_verified = False
        user.save()
        
        url = reverse('customer_login')
        response = api_client.post(url, {'username': 'unverified', 'password': 'pass'})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data['code'] == 'email_not_verified'

    def test_otp_verification_flows(self, api_client, mock_sms_request):
        # Trigger phone otp request and verify (Lines 288+)
        user = User.objects.create_user(username='otp_user', password='pass', phone_number='+911234567890')
        api_client.force_authenticate(user=user)
        
        # 1. Request Phone OTP
        url_req = reverse('request_phone_verification')
        response = api_client.post(url_req)
        assert response.status_code == status.HTTP_200_OK
        
        otp_obj = OTPVerification.objects.get(user=user)
        code = otp_obj.otp_code
        
        # 2. Verify Phone OTP
        url_verify = reverse('verify_otp')
        response = api_client.post(url_verify, {'phone_number': user.phone_number, 'otp_code': code})
        assert response.status_code == status.HTTP_200_OK
        
        user.refresh_from_db()
        assert user.is_phone_verified is True

    def test_email_otp_verification_success(self, api_client):
        # Trigger verify_email_otp (Lines 626+)
        user = User.objects.create_user(username='email_user', password='pass', email='test@example.com')
        import datetime
        from django.utils import timezone
        otp = EmailOTPVerification.objects.create(
            user=user, 
            email=user.email, 
            otp_code='1234', 
            expires_at=timezone.now() + datetime.timedelta(minutes=10)
        )
        
        url = reverse('verify_email_otp')
        response = api_client.post(url, {'email': user.email, 'otp_code': '1234'})
        assert response.status_code == status.HTTP_200_OK
        
        user.refresh_from_db()
        assert user.is_email_verified is True

    def test_password_flows_forgot_reset(self, api_client, mock_sms_request, mock_email_send):
        # Trigger forgot_password and reset_password branches
        user = User.objects.create_user(username='pass_user', password='oldpass', phone_number='+919876543210', email='pass@example.com')
        
        # 1. Forgot Password (Phone)
        url_forgot = reverse('forgot_password')
        response = api_client.post(url_forgot, {'phone_number': '+919876543210'})
        assert response.status_code == status.HTTP_200_OK
        
        otp_code = OTPVerification.objects.get(user=user).otp_code
        
        # 2. Reset Password (Phone)
        url_reset = reverse('reset_password')
        reset_data = {
            'phone_number': '+919876543210',
            'otp_code': otp_code,
            'new_password': 'NewPassword@123',
            'confirm_password': 'NewPassword@123'
        }
        response = api_client.post(url_reset, reset_data, format='json')
        if response.status_code != 200:
            pytest.fail(f"Reset Password Error: {response.data}")
        assert response.status_code == status.HTTP_200_OK
        
    def test_resend_otp_flow(self, api_client, mock_sms_request):
        # Trigger resend_otp (Line 683)
        user = User.objects.create_user(username='resend_user', password='pass', phone_number='+917778889990', user_type='customer')
        url = reverse('resend_otp')
        
        # 1. Success
        response = api_client.post(url, {'phone_number': '+917778889990'}, format='json')
        assert response.status_code == status.HTTP_200_OK

    def test_register_device_flow(self, api_client):
        # Trigger register_device (Line 751)
        user = User.objects.create_user(username='device_user', password='pass')
        api_client.force_authenticate(user=user)
        
        url = reverse('register_device')
        data = {
            'registration_id': 'fcm_token_123',
            'type': 'ios',
            'name': 'iPhone 13'
        }
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK

    def test_reset_password_email_flow(self, api_client, mock_email_send):
        # Trigger reset_password_email (Line 1004)
        user = User.objects.create_user(username='reset_e_user', password='oldpass', email='reset_e@example.com')
        
        # 1. Forgot Email Password
        url_forgot = reverse('forgot_password_email')
        api_client.post(url_forgot, {'email': 'reset_e@example.com'}, format='json')
        
        otp_obj = EmailOTPVerification.objects.get(user=user)
        code = otp_obj.otp_code
        
        # 2. Reset Password Email
        url_reset = reverse('reset_password_email')
        data = {
            'email': 'reset_e@example.com',
            'otp_code': code,
            'new_password': 'NewPassword@123',
            'confirm_password': 'NewPassword@123'
        }
        response = api_client.post(url_reset, data, format='json')
        assert response.status_code == status.HTTP_200_OK

    def test_profile_management(self, api_client):
        # Trigger get_profile and update_profile (Lines 574, 592)
        user = User.objects.create_user(username='profile_user', password='pass')
        api_client.force_authenticate(user=user)
        
        # 1. Get Profile
        url_get = reverse('get_profile')
        response = api_client.get(url_get)
        assert response.status_code == status.HTTP_200_OK
        
        # 2. Update Profile
        url_up = reverse('update_profile')
        response = api_client.patch(url_up, {'first_name': 'NewName'}, format='json')
        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == 'NewName'

    def test_change_password_success(self, api_client):
        # Trigger change_password (Line 20 in URLS)
        user = User.objects.create_user(username='change_pass', password='OldPassword@123')
        api_client.force_authenticate(user=user)
        
        url = reverse('change_password')
        data = {
            'old_password': 'OldPassword@123',
            'new_password': 'NewPassword@123',
            'confirm_password': 'NewPassword@123'
        }
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK

    def test_otp_failure_cases(self, api_client, mock_sms_request):
        # Trigger failure branches in verify_otp (Lines 473, 480, 487, 560)
        user = User.objects.create_user(username='fail_otp', password='pass', phone_number='+911112223334')
        url_verify = reverse('verify_otp')
        
        # 1. Invalid OTP request (No OTP record exists)
        response = api_client.post(url_verify, {'phone_number': '+911112223334', 'otp_code': '1234'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        
        # Create OTP record
        from django.utils import timezone
        import datetime
        otp = OTPVerification.objects.create(
            user=user, 
            phone_number=user.phone_number, 
            otp_code='1234', 
            secret_key='key',
            expires_at=timezone.now() - datetime.timedelta(minutes=1) # Expired
        )
        
        # 2. Expired OTP
        response = api_client.post(url_verify, {'phone_number': user.phone_number, 'otp_code': '1234'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_firebase_verification_flow(self, api_client, mock_firebase_auth):
        # Trigger Firebase verification logic (Lines 371-406)
        user = User.objects.create_user(username='fb_user', password='pass', phone_number='+915556667778')
        mock_firebase_auth.return_value = {'phone_number': '+915556667778'}
        
        url = reverse('verify_otp')
        data = {
            'phone_number': '+915556667778',
            'firebase_token': 'fake_token'
        }
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.is_phone_verified is True

    def test_logout_flow(self, api_client):
        # Trigger logout (Line 1113)
        user = User.objects.create_user(username='logout_user', password='pass')
        api_client.force_authenticate(user=user)
        
        url = reverse('logout')
        response = api_client.post(url)
        assert response.status_code == status.HTTP_200_OK

    def test_verify_otp_full_failures(self, api_client, mock_sms_request):
        # Trigger branches in verify_otp (Lines 487, 556)
        user = User.objects.create_user(username='otp_fails', password='pass', phone_number='+916667778889')
        # Create valid OTP record
        from django.utils import timezone
        otp = OTPVerification.objects.create(
            user=user, 
            phone_number=user.phone_number, 
            otp_code='1234', 
            secret_key='key',
            expires_at=timezone.now() + timezone.timedelta(minutes=5),
            attempts=0
        )
        
        url = reverse('verify_otp')
        # 1. Invalid Code
        response = api_client.post(url, {'phone_number': user.phone_number, 'otp_code': 'WRONG'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        otp.refresh_from_db()
        assert otp.attempts == 1
        
        # 2. Max Attempts
        otp.attempts = 5
        otp.save()
        response = api_client.post(url, {'phone_number': user.phone_number, 'otp_code': '1234'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error'] == 'Maximum OTP attempts exceeded'

    def test_verify_email_otp_failures(self, api_client):
        # Trigger failure branches in verify_email_otp (Lines 640, 656)
        user = User.objects.create_user(username='email_fail', password='pass', email='fail@example.com')
        from django.utils import timezone
        import datetime
        otp = EmailOTPVerification.objects.create(
            user=user, 
            email=user.email, 
            otp_code='1234', 
            secret_key='key',
            expires_at=timezone.now() - datetime.timedelta(minutes=1) # Expired
        )
        
        url = reverse('verify_email_otp')
        # 1. Expired
        response = api_client.post(url, {'email': user.email, 'otp_code': '1234'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        
        # 2. Invalid code
        otp.expires_at = timezone.now() + datetime.timedelta(minutes=10)
        otp.save()
        response = api_client.post(url, {'email': user.email, 'otp_code': 'WRONG'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
