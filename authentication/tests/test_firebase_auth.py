from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from authentication.models import User
from unittest.mock import patch

class FirebaseAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.verify_url = reverse('verify_otp')
        self.phone_number = '+1234567890'
        self.user = User.objects.create_user(
            username='testuser',
            password='testpassword',
            phone_number=self.phone_number,
            user_type='customer'
        )

    @patch('authentication.views.verify_firebase_id_token')
    def test_firebase_auth_success(self, mock_verify):
        # Mock successful Firebase verification
        mock_verify.return_value = {'uid': 'some-uid', 'phone_number': self.phone_number}

        data = {
            'phone_number': self.phone_number,
            'firebase_token': 'valid-token'
        }

        response = self.client.post(self.verify_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('tokens', response.data)
        
        # Reload user to check verification status
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_phone_verified)
        self.assertTrue(self.user.is_active)

    @patch('authentication.views.verify_firebase_id_token')
    def test_firebase_auth_invalid_token(self, mock_verify):
        # Mock failed verification
        mock_verify.return_value = None

        data = {
            'phone_number': self.phone_number,
            'firebase_token': 'invalid-token'
        }

        response = self.client.post(self.verify_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], 'Invalid Firebase Token')

    def test_missing_credentials(self):
        data = {
            'phone_number': self.phone_number
            # No otp or token
        }
        response = self.client.post(self.verify_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
