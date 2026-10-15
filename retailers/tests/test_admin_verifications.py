from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status
from authentication.models import User
from retailers.models import RetailerProfile


class RetailerVerificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Regular retailer
        self.retailer_user = User.objects.create_user(
            username='testretailer',
            email='retailer@shop.com',
            phone_number='+919876543210',
            password='Password@123',
            user_type='retailer'
        )
        self.retailer_profile = RetailerProfile.objects.create(
            user=self.retailer_user,
            shop_name='Test Kirana',
            verification_status='pending',
            is_verified=False,
            is_active=False
        )

        # Admin user
        self.admin_user = User.objects.create_user(
            username='platformadmin',
            email='admin@ordereasy.in',
            password='AdminPassword@123',
            user_type='customer'
        )

    def test_open_signup_without_access_code(self):
        """Verify retailer signup succeeds without access_code"""
        payload = {
            'username': 'newretailer',
            'email': 'newretailer@shop.com',
            'phone_number': '+919999988888',
            'password': 'StrongPassword@123',
            'password_confirm': 'StrongPassword@123',
        }
        response = self.client.post('/api/auth/retailer/signup/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('user', response.data)
        self.assertEqual(response.data['user']['verification_status'], 'pending')
        self.assertFalse(response.data['user']['is_verified'])

        # Check DB
        new_profile = RetailerProfile.objects.get(user__username='newretailer')
        self.assertEqual(new_profile.verification_status, 'pending')
        self.assertFalse(new_profile.is_verified)
        self.assertFalse(new_profile.is_active)
        self.assertEqual(new_profile.contact_email, 'newretailer@shop.com')

        # Check Retailer Profile endpoint returns autofilled contact_email
        self.client.force_authenticate(user=new_profile.user)
        profile_res = self.client.get('/api/retailer/profile/')
        self.assertEqual(profile_res.status_code, status.HTTP_200_OK)
        self.assertEqual(profile_res.data['contact_email'], 'newretailer@shop.com')

    @override_settings(ADMIN_EMAILS=['admin@ordereasy.in'])
    def test_user_profile_admin_flag(self):
        """Admin email gets is_admin=True, regular user gets is_admin=False"""
        self.client.force_authenticate(user=self.admin_user)
        res_admin = self.client.get('/api/auth/profile/')
        self.assertEqual(res_admin.status_code, status.HTTP_200_OK)
        self.assertTrue(res_admin.data['is_admin'])

        self.client.force_authenticate(user=self.retailer_user)
        res_retailer = self.client.get('/api/auth/profile/')
        self.assertEqual(res_retailer.status_code, status.HTTP_200_OK)
        self.assertFalse(res_retailer.data['is_admin'])
        self.assertEqual(res_retailer.data['verification_status'], 'pending')

    @override_settings(ADMIN_EMAILS=['admin@ordereasy.in'])
    def test_non_admin_cannot_access_verification_endpoints(self):
        """Regular users are forbidden from admin verification APIs"""
        self.client.force_authenticate(user=self.retailer_user)
        response = self.client.get('/api/retailer/admin/verifications/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        action_response = self.client.post(
            f'/api/retailer/admin/verifications/{self.retailer_profile.id}/action/',
            {'action': 'approve'},
            format='json'
        )
        self.assertEqual(action_response.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(ADMIN_EMAILS=['admin@ordereasy.in'])
    def test_admin_can_list_and_approve_retailer(self):
        """Admin can list pending retailers and approve them"""
        self.client.force_authenticate(user=self.admin_user)

        # List verifications
        list_res = self.client.get('/api/retailer/admin/verifications/?status=pending')
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertEqual(list_res.data['counts']['pending'], 1)
        self.assertEqual(len(list_res.data['results']), 1)
        self.assertEqual(list_res.data['results'][0]['shop_name'], 'Test Kirana')

        # Approve
        approve_res = self.client.post(
            f'/api/retailer/admin/verifications/{self.retailer_profile.id}/action/',
            {'action': 'approve'},
            format='json'
        )
        self.assertEqual(approve_res.status_code, status.HTTP_200_OK)
        self.assertEqual(approve_res.data['verification_status'], 'approved')

        # Check DB
        self.retailer_profile.refresh_from_db()
        self.assertEqual(self.retailer_profile.verification_status, 'approved')
        self.assertTrue(self.retailer_profile.is_verified)
        self.assertTrue(self.retailer_profile.is_active)

    @override_settings(ADMIN_EMAILS=['admin@ordereasy.in'])
    def test_admin_can_reject_retailer_with_reason(self):
        """Admin can reject a retailer with custom reason"""
        self.client.force_authenticate(user=self.admin_user)

        reject_res = self.client.post(
            f'/api/retailer/admin/verifications/{self.retailer_profile.id}/action/',
            {'action': 'reject', 'reason': 'Invalid business documents provided'},
            format='json'
        )
        self.assertEqual(reject_res.status_code, status.HTTP_200_OK)
        self.assertEqual(reject_res.data['verification_status'], 'rejected')

        # Check DB
        self.retailer_profile.refresh_from_db()
        self.assertEqual(self.retailer_profile.verification_status, 'rejected')
        self.assertFalse(self.retailer_profile.is_verified)
        self.assertFalse(self.retailer_profile.is_active)
        self.assertEqual(self.retailer_profile.rejection_reason, 'Invalid business documents provided')

    def test_customer_cannot_see_pending_or_rejected_retailers(self):
        """Customer retailer listing and detail APIs only expose approved retailers"""
        # 1. Retailer is pending -> should NOT show in list or detail
        list_res = self.client.get('/api/retailer/')
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        # Results can be a list or paginated dict
        results = list_res.data.get('results', list_res.data) if isinstance(list_res.data, dict) else list_res.data
        shop_ids = [s['id'] for s in results]
        self.assertNotIn(self.retailer_profile.id, shop_ids)

        detail_res = self.client.get(f'/api/retailer/{self.retailer_profile.id}/')
        self.assertEqual(detail_res.status_code, status.HTTP_404_NOT_FOUND)

        # 2. Retailer is approved -> should show in list and detail
        self.retailer_profile.verification_status = 'approved'
        self.retailer_profile.is_verified = True
        self.retailer_profile.is_active = True
        self.retailer_profile.save()

        list_res = self.client.get('/api/retailer/')
        results = list_res.data.get('results', list_res.data) if isinstance(list_res.data, dict) else list_res.data
        shop_ids = [s['id'] for s in results]
        self.assertIn(self.retailer_profile.id, shop_ids)

        detail_res = self.client.get(f'/api/retailer/{self.retailer_profile.id}/')
        self.assertEqual(detail_res.status_code, status.HTTP_200_OK)

        # 3. Retailer is rejected -> should NOT show
        self.retailer_profile.verification_status = 'rejected'
        self.retailer_profile.is_verified = False
        self.retailer_profile.is_active = False
        self.retailer_profile.save()

        list_res = self.client.get('/api/retailer/')
        results = list_res.data.get('results', list_res.data) if isinstance(list_res.data, dict) else list_res.data
        shop_ids = [s['id'] for s in results]
        self.assertNotIn(self.retailer_profile.id, shop_ids)

        detail_res = self.client.get(f'/api/retailer/{self.retailer_profile.id}/')
        self.assertEqual(detail_res.status_code, status.HTTP_404_NOT_FOUND)
