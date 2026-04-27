import pytest
from rest_framework.exceptions import ValidationError
from authentication.serializers import (
    UserRegistrationSerializer, UserLoginSerializer, OTPRequestSerializer,
    OTPVerificationSerializer, UserProfileSerializer, TokenSerializer,
    PasswordChangeSerializer, ForgotPasswordSerializer, ResetPasswordConfirmSerializer,
    ForgotPasswordEmailSerializer, ResetPasswordEmailConfirmSerializer
)
from authentication.models import User
from retailers.models import RetailerProfile

@pytest.mark.django_db
class TestAuthenticationSerializers:
    def test_user_registration_serializer_password_mismatch(self):
        data = {
            'username': 'testregistration',
            'password': 'Password123!',
            'password_confirm': 'Password124!',
            'user_type': 'customer'
        }
        serializer = UserRegistrationSerializer(data=data)
        assert not serializer.is_valid()
        assert 'password' in serializer.errors

    def test_user_registration_serializer_phone_exists(self):
        User.objects.create(username='existing', phone_number='+11234567890')
        data = {
            'username': 'newuser',
            'password': 'Password123!',
            'password_confirm': 'Password123!',
            'phone_number': '+11234567890',
            'user_type': 'customer'
        }
        serializer = UserRegistrationSerializer(data=data)
        assert not serializer.is_valid()
        assert 'phone_number' in serializer.errors

    def test_user_login_serializer_by_email(self):
        User.objects.create_user(username='logger', email='login@test.com', password='Password123!')
        serializer = UserLoginSerializer(data={'username': 'login@test.com', 'password': 'Password123!'})
        assert serializer.is_valid()
        assert serializer.validated_data['user'].username == 'logger'

    def test_user_login_serializer_by_phone(self):
        User.objects.create_user(username='phlogger', phone_number='+11234567000', password='Password123!')
        serializer = UserLoginSerializer(data={'username': '+11234567000', 'password': 'Password123!'})
        assert serializer.is_valid()
        assert serializer.validated_data['user'].username == 'phlogger'
        
    def test_user_login_serializer_invalid_credentials(self):
        User.objects.create_user(username='phlogger2', password='Password123!')
        serializer = UserLoginSerializer(data={'username': 'phlogger2', 'password': 'WrongPassword123!'})
        assert not serializer.is_valid()
        assert 'non_field_errors' in serializer.errors

    def test_user_login_serializer_disabled_account(self):
        User.objects.create_user(username='disabled', password='Password123!', is_active=False)
        serializer = UserLoginSerializer(data={'username': 'disabled', 'password': 'Password123!'})
        assert not serializer.is_valid()

    def test_user_login_serializer_missing_fields(self):
        serializer = UserLoginSerializer(data={})
        assert not serializer.is_valid()

    def test_otp_request_serializer(self):
        s1 = OTPRequestSerializer(data={'phone_number': '12345'})
        assert not s1.is_valid() 
        
        s2 = OTPRequestSerializer(data={'phone_number': '+123'})
        assert not s2.is_valid() 
        
        s3 = OTPRequestSerializer(data={'phone_number': '+1234567890'})
        assert s3.is_valid()

    def test_otp_verification_serializer(self):
        s1 = OTPVerificationSerializer(data={'phone_number': '+1234567890'})
        assert not s1.is_valid() 
        
        s2 = OTPVerificationSerializer(data={'phone_number': '+1234567890', 'otp_code': '12'})
        assert not s2.is_valid() 

    def test_user_profile_shop_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        user = User.objects.create(username='retailerurl', user_type='retailer')
        rp = RetailerProfile.objects.create(user=user, shop_name='My Shop')
        
        serializer = UserProfileSerializer(user)
        assert serializer.data['shop_image'] is None
        
        # Test image path coverage
        rp.shop_image = SimpleUploadedFile("test_image.jpg", b"file_content", content_type="image/jpeg")
        rp.save()
        assert UserProfileSerializer(user).data['shop_image'] is not None

    def test_token_serializer(self):
        user = User.objects.create(username='tokensrz')
        serializer = TokenSerializer()
        data = serializer.create({'user': user})
        assert 'access_token' in data
        assert 'refresh_token' in data
        
    def test_password_change_serializer(self):
        class MockRequest:
            def __init__(self, user):
                self.user = user
                
        user = User.objects.create_user(username='pwchange', password='OldPassword123!')
        req = MockRequest(user)
        
        s = PasswordChangeSerializer(data={
            'old_password': 'WrongPassword!',
            'new_password': 'NewPassword123!',
            'confirm_password': 'NewPassword123!'
        }, context={'request': req})
        assert not s.is_valid()
        
        s2 = PasswordChangeSerializer(data={
            'old_password': 'OldPassword123!',
            'new_password': 'NewPassword123!',
            'confirm_password': 'Mismatch123!'
        }, context={'request': req})
        assert not s2.is_valid()

    def test_forgot_password_serializer(self):
        s = ForgotPasswordSerializer(data={'phone_number': '+12345670111'})
        assert not s.is_valid() 
        
        User.objects.create(username='fpp', phone_number='+12345670111')
        s2 = ForgotPasswordSerializer(data={'phone_number': '+12345670111'})
        assert s2.is_valid()

    def test_reset_password_confirm_serializer(self):
        s = ResetPasswordConfirmSerializer(data={
            'phone_number': '+11',
            'new_password': 'P1',
            'confirm_password': 'P2'
        })
        assert not s.is_valid() 
        
        s2 = ResetPasswordConfirmSerializer(data={
            'phone_number': '+11',
            'new_password': 'Password123!',
            'confirm_password': 'Password123!'
        })
        assert not s2.is_valid() 

    def test_forgot_password_email_serializer(self):
        s = ForgotPasswordEmailSerializer(data={'email': 'missing@domain.com'})
        assert not s.is_valid()
        
        User.objects.create(username='em1', email='missing@domain.com')
        s2 = ForgotPasswordEmailSerializer(data={'email': 'missing@domain.com'})
        assert s2.is_valid()

    def test_reset_password_email_confirm_serializer(self):
        s = ResetPasswordEmailConfirmSerializer(data={
            'email': 'a@b.com',
            'otp_code': '123456',
            'new_password': 'p1',
            'confirm_password': 'p2'
        })
        assert not s.is_valid()
