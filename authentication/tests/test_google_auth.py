from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from authentication.models import User
from customers.models import CustomerProfile
from unittest.mock import patch

class GoogleAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.google_login_url = reverse('customer_google_login')
        self.existing_email = 'existing@gmail.com'
        self.existing_phone = '+919876543210'
        
        # Create an existing customer
        self.existing_user = User.objects.create_user(
            username=self.existing_phone,
            email=self.existing_email,
            phone_number=self.existing_phone,
            password='some-password',
            user_type='customer',
            is_email_verified=True
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
    def test_new_user_signup_success(self, mock_verify):
        new_email = 'newuser@gmail.com'
        new_phone = '9876543211' # Will be cleaned to +919876543211
        mock_verify.return_value = {
            'email': new_email,
            'name': 'New Customer'
        }
        
        # Call with token and new phone number
        response = self.client.post(
            self.google_login_url, 
            {
                'firebase_token': 'valid-token',
                'phone_number': new_phone
            }, 
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'success')
        self.assertIn('tokens', response.data)
        
        # Verify user was created correctly
        user = User.objects.get(email=new_email)
        self.assertEqual(user.username, '+91' + new_phone)
        self.assertEqual(user.phone_number, '+91' + new_phone)
        self.assertTrue(user.is_email_verified)
        self.assertFalse(user.is_phone_verified)
        self.assertEqual(user.user_type, 'customer')
        
        # Verify CustomerProfile was lazy created
        self.assertTrue(CustomerProfile.objects.filter(user=user).exists())

    @patch('authentication.views.verify_firebase_id_token')
    def test_phone_number_collision(self, mock_verify):
        new_email = 'newuser2@gmail.com'
        mock_verify.return_value = {
            'email': new_email,
            'name': 'New Customer 2'
        }
        
        # Call with an already registered phone number
        response = self.client.post(
            self.google_login_url, 
            {
                'firebase_token': 'valid-token',
                'phone_number': self.existing_phone
            }, 
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already registered', response.data['error'])

    @patch('authentication.views.verify_firebase_id_token')
    def test_claim_shadow_user_success(self, mock_verify):
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
        
        response = self.client.post(
            self.google_login_url, 
            {
                'firebase_token': 'valid-token',
                'phone_number': '9876543212' # Matches shadow_phone (last 10 digits)
            }, 
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify shadow user was updated
        shadow_user.refresh_from_db()
        self.assertEqual(shadow_user.email, shadow_email)
        self.assertEqual(shadow_user.first_name, 'Claimed Shadow User')
        self.assertEqual(shadow_user.registration_status, 'registered')
        self.assertTrue(shadow_user.is_email_verified)
        self.assertFalse(shadow_user.is_phone_verified)
        
        # Verify CustomerProfile was lazy created
        self.assertTrue(CustomerProfile.objects.filter(user=shadow_user).exists())
