import pytest
from django.urls import reverse
from rest_framework import status
from django.conf import settings
from .factories import UserFactory, RetailerUserFactory
from authentication.models import User, EmailOTPVerification, OTPVerification, UserSession
from django.utils import timezone
from datetime import timedelta

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
        assert EmailOTPVerification.objects.filter(email="customer@example.com").exists()
        assert mock_email_send.called

    def test_retailer_login(self, api_client):
        user = User.objects.create_user(username="r_login", user_type="retailer", password="mypassword", is_active=True)
        # Success
        response = api_client.post(reverse('retailer_login'), {"username": "r_login", "password": "mypassword"})
        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data['tokens']
        
        # Wrong password
        res2 = api_client.post(reverse('retailer_login'), {"username": "r_login", "password": "wrong"})
        assert res2.status_code == status.HTTP_400_BAD_REQUEST
        
        # Inactive
        user.is_active = False
        user.save()
        res3 = api_client.post(reverse('retailer_login'), {"username": "r_login", "password": "mypassword"})
        assert res3.status_code == status.HTTP_400_BAD_REQUEST
        
        # Missing fields
        res4 = api_client.post(reverse('retailer_login'), {"username": "r_login"})
        assert res4.status_code == status.HTTP_400_BAD_REQUEST

    def test_customer_login_success(self, api_client):
        user = UserFactory(username="login_user", is_email_verified=True)
        user.set_password("mypassword")
        user.save()
        
        url = reverse('customer_login')
        payload = {"username": "login_user", "password": "mypassword"}
        response = api_client.post(url, payload)
        
        assert response.status_code == status.HTTP_200_OK
        assert 'tokens' in response.data

    def test_customer_login_unverified_email(self, api_client):
        user = UserFactory(username="unverified_user", is_email_verified=False)
        user.set_password("mypassword")
        user.save()
        
        url = reverse('customer_login')
        payload = {"username": "unverified_user", "password": "mypassword"}
        response = api_client.post(url, payload)
        
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data['code'] == 'email_not_verified'

    def test_profile_endpoints(self, api_client):
        user = UserFactory(username="profuser", is_email_verified=True)
        user.set_password("mypassword")
        user.save()
        
        # Unauthorized access
        res = api_client.get(reverse('get_profile'))
        assert res.status_code == status.HTTP_401_UNAUTHORIZED
        
        # Authorized Get 
        api_client.force_authenticate(user=user)
        res = api_client.get(reverse('get_profile'))
        assert res.status_code == status.HTTP_200_OK
        
        # Update Profile
        res = api_client.put(reverse('update_profile'), {"first_name": "NewName"})
        assert res.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "NewName"
        
        # Invalid Update Profile
        res = api_client.put(reverse('update_profile'), {"email": "invalidemail"}) # assume validation fails if missing @, actually ModelSerializer handles it
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_change_password(self, api_client):
        user = UserFactory(username="pwuser", is_email_verified=True)
        user.set_password("mypassword")
        user.save()
        
        api_client.force_authenticate(user=user)
        # Invalid old password
        res = api_client.post(reverse('change_password'), {
            "old_password": "wrong",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!"
        })
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        
        # Success
        res2 = api_client.post(reverse('change_password'), {
            "old_password": "mypassword",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!"
        })
        assert res2.status_code == status.HTTP_200_OK

    def test_logout(self, api_client):
        user = UserFactory(username="logoutuser")
        api_client.force_authenticate(user=user)
        
        # Missing token
        assert api_client.post(reverse('logout')).status_code == status.HTTP_200_OK
        
        # Fake Token Logout
        res = api_client.post(reverse('logout'), {"refresh_token": "faketoken"})
        assert res.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_forgot_password_phone(self, api_client, mock_sms_request):
        user = User.objects.create_user(username="fpphone", phone_number="+1112223333", password="123")
        
        # Request Phone OTP
        # Valid 
        res = api_client.post(reverse('forgot_password'), {"phone_number": "+1112223333"})
        assert res.status_code == status.HTTP_200_OK
        
        # Reset Password Confirm
        # Missing OTP
        res2 = api_client.post(reverse('reset_password'), {
            "phone_number": "+1112223333",
            "new_password": "StrongPassword123!",
            "confirm_password": "StrongPassword123!"
        })
        assert res2.status_code == status.HTTP_400_BAD_REQUEST
        
        # Invalid OTP
        res3 = api_client.post(reverse('reset_password'), {
            "phone_number": "+1112223333",
            "otp_code": "000000",
            "new_password": "StrongPassword123!",
            "confirm_password": "StrongPassword123!"
        })
        assert res3.status_code == status.HTTP_400_BAD_REQUEST

    def test_forgot_password_email(self, api_client, mock_email_send):
        user = User.objects.create_user(username="fpemail", email="test@fp.com", password="123")
        
        # Invalid Form
        assert api_client.post(reverse('forgot_password_email'), {}).status_code == status.HTTP_400_BAD_REQUEST
        
        # Success Send
        res = api_client.post(reverse('forgot_password_email'), {"email": "test@fp.com"})
        assert res.status_code == status.HTTP_200_OK
        
        # Confirm with wrong OTP
        res2 = api_client.post(reverse('reset_password_email'), {
            "email": "test@fp.com",
            "otp_code": "000000",
            "new_password": "StrongPassword123!",
            "confirm_password": "StrongPassword123!"
        })
        assert res2.status_code == status.HTTP_400_BAD_REQUEST
        
        # Setup real OTP to confirm
        # Wait, the previous POST to forgot_password_email created an OTP. We should fetch it.
        otp_obj = EmailOTPVerification.objects.get(email="test@fp.com")
        res3 = api_client.post(reverse('reset_password_email'), {
            "email": "test@fp.com",
            "otp_code": otp_obj.otp_code,
            "new_password": "StrongPassword123!",
            "confirm_password": "StrongPassword123!"
        })
        assert res3.status_code == status.HTTP_200_OK
