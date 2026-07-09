from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from authentication.models import User, OTPVerification
from customers.models import CustomerProfile
from unittest.mock import patch

class GoogleAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.google_login_url = reverse('customer_google_login')
        self.existing_email = 'existing@gmail.com'
        self.existing_phone = '+919876543200'
        
        # Create an existing customer
        self.existing_user = User.objects.create_user(
            username=self.existing_phone,
            email=self.existing_email,
            phone_number=self.existing_phone,
            password='some-password',
            user_type='customer',
            is_email_verified=True,
            is_phone_verified=True
        )

        # Create a retailer user with another phone number
        self.retailer_phone = '+919876543299'
        self.retailer_user = User.objects.create_user(
            username=self.retailer_phone,
            email='retailer@gmail.com',
            phone_number=self.retailer_phone,
            password='retailer-password',
            user_type='retailer'
        )

    def test_missing_firebase_token(self):
        response = self.client.post(self.google_login_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], 'Firebase token is required')

    @patch('authentication.views.verify_firebase_id_token')
    def test_invalid_firebase_token(self, mock_verify):
        mock_verify.return_value = None
        response = self.client.post(
            self.google_login_url, 
            {'firebase_token': 'invalid-token'}, 
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], 'Invalid Firebase token')

    @patch('authentication.views.verify_firebase_id_token')
    def test_existing_user_login_success(self, mock_verify):
        mock_verify.return_value = {
            'email': self.existing_email,
            'name': 'Existing Customer'
        }
        response = self.client.post(
            self.google_login_url, 
            {'firebase_token': 'valid-token'}, 
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'success')
        self.assertIn('tokens', response.data)
        self.assertEqual(response.data['user']['email'], self.existing_email)

    @patch('authentication.views.verify_firebase_id_token')
    def test_new_user_phone_required_status(self, mock_verify):
        new_email = 'newuser@gmail.com'
        mock_verify.return_value = {
            'email': new_email,
            'name': 'New Customer'
        }
        response = self.client.post(
            self.google_login_url, 
            {'firebase_token': 'valid-token'}, 
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'phone_required')
        self.assertEqual(response.data['email'], new_email)

    @patch('authentication.views.verify_firebase_id_token')
    def test_new_user_signup_success_no_otp(self, mock_verify):
        new_email = 'newuser@gmail.com'
        new_phone = '9876543211' # Will be cleaned to +919876543211
        mock_verify.return_value = {
            'email': new_email,
            'name': 'New Customer'
        }
        
        # Call with token and completely new phone number
        response = self.client.post(
            self.google_login_url, 
            {
                'firebase_token': 'valid-token',
                'phone_number': new_phone
            }, 
            format='json'
        )
        
        # For a brand new number, registration is immediate with zero SMS OTP cost (deferred to 1st order)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'success')
        self.assertIn('tokens', response.data)
        
        # Verify user was created correctly
        user = User.objects.get(email=new_email)
        self.assertEqual(user.username, '+91' + new_phone)
        self.assertEqual(user.phone_number, '+91' + new_phone)
        self.assertTrue(user.is_email_verified)
        self.assertFalse(user.is_phone_verified)  # OTP deferred
        self.assertEqual(user.user_type, 'customer')
        
        # Verify CustomerProfile was lazy created
        self.assertTrue(CustomerProfile.objects.filter(user=user).exists())

    @patch('authentication.views.verify_firebase_id_token')
    def test_retailer_phone_number_collision(self, mock_verify):
        new_email = 'newcustomer@gmail.com'
        mock_verify.return_value = {
            'email': new_email,
            'name': 'New Customer'
        }
        
        # Call with an already registered retailer phone number
        response = self.client.post(
            self.google_login_url, 
            {
                'firebase_token': 'valid-token',
                'phone_number': self.retailer_phone
            }, 
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('registered as a Retailer account', response.data['error'])

    @patch('authentication.views.verify_firebase_id_token')
    @patch('authentication.views.send_sms_otp')
    def test_claim_shadow_user_otp_required_and_verify(self, mock_send_sms, mock_verify):
        shadow_email = 'shadow@gmail.com'
        shadow_phone = '+919876543212'
        
        # Create shadow user
        shadow_user = User.objects.create_user(
            username=shadow_phone,
            phone_number=shadow_phone,
            user_type='customer',
            registration_status='shadow'
        )
        
        mock_verify.return_value = {
            'email': shadow_email,
            'name': 'Claimed Shadow User'
        }
        mock_send_sms.return_value = True
        
        # Call 1: Input shadow phone number -> Backend triggers OTP
        response1 = self.client.post(
            self.google_login_url, 
            {
                'firebase_token': 'valid-token',
                'phone_number': shadow_phone
            }, 
            format='json'
        )
        
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response1.data['status'], 'otp_required')
        
        # Retreive generated OTP from DB
        otp_record = OTPVerification.objects.get(phone_number=shadow_phone)
        self.assertIsNotNone(otp_record.otp_code)
        
        # Call 2: Submit with incorrect OTP -> Should fail
        response2 = self.client.post(
            self.google_login_url, 
            {
                'firebase_token': 'valid-token',
                'phone_number': shadow_phone,
                'otp_code': '000000' # Wrong OTP
            }, 
            format='json'
        )
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Invalid OTP code', response2.data['error'])
        
        # Call 3: Submit with correct OTP -> Should succeed
        response3 = self.client.post(
            self.google_login_url, 
            {
                'firebase_token': 'valid-token',
                'phone_number': shadow_phone,
                'otp_code': otp_record.otp_code
            }, 
            format='json'
        )
        self.assertEqual(response3.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response3.data['status'], 'success')
        
        # Verify shadow user was updated and claimed
        shadow_user.refresh_from_db()
        self.assertEqual(shadow_user.email, shadow_email)
        self.assertEqual(shadow_user.first_name, 'Claimed Shadow User')
        self.assertEqual(shadow_user.registration_status, 'registered')
        self.assertTrue(shadow_user.is_email_verified)
        self.assertTrue(shadow_user.is_phone_verified)  # Verified via OTP at claim
        
        # Verify CustomerProfile was lazy created
        self.assertTrue(CustomerProfile.objects.filter(user=shadow_user).exists())

    @patch('authentication.views.verify_firebase_id_token')
    @patch('authentication.views.send_sms_otp')
    def test_existing_customer_otp_link_flow(self, mock_send_sms, mock_verify):
        new_google_email = 'brandnewgoogle@gmail.com'
        mock_verify.return_value = {
            'email': new_google_email,
            'name': 'Existing Customer Google Profile'
        }
        mock_send_sms.return_value = True
        
        # Call 1: Input existing customer's phone -> Backend triggers OTP linking
        response1 = self.client.post(
            self.google_login_url, 
            {
                'firebase_token': 'valid-token',
                'phone_number': self.existing_phone
            }, 
            format='json'
        )
        
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response1.data['status'], 'otp_required')
        
        # Retreive generated OTP
        otp_record = OTPVerification.objects.get(phone_number=self.existing_phone)
        
        # Call 2: Verify with correct OTP -> Should link successfully
        response2 = self.client.post(
            self.google_login_url, 
            {
                'firebase_token': 'valid-token',
                'phone_number': self.existing_phone,
                'otp_code': otp_record.otp_code
            }, 
            format='json'
        )
        
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response2.data['status'], 'success')
        
        # Verify existing user's email was updated to Google Email
        self.existing_user.refresh_from_db()
        self.assertEqual(self.existing_user.email, new_google_email)
        self.assertTrue(self.existing_user.is_email_verified)
        self.assertTrue(self.existing_user.is_phone_verified)
