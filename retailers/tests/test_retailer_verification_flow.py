"""Retailer verification flow (docs/requirements/retailer-verification.md)."""
import io
import shutil
import tempfile
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from authentication.models import User
from common.content_rules import check_text
from retailers.models import RetailerProfile, RetailerVerificationDocument, VerificationEvent
from retailers.private_storage import private_document_storage
from retailers.verification import gstin_checksum_ok, run_checks

VALID_GSTIN = '27AAPFU0939F1ZV'  # public sample GSTIN with a correct checksum


def png_bytes():
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), 'white').save(buf, 'PNG')
    return buf.getvalue()


class _Base(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        override = override_settings(PRIVATE_MEDIA_ROOT=self.tmp, PRIVATE_DOCS_BUCKET='',
                                     ADMIN_EMAILS=['admin@ordereasy.in'])
        override.enable()
        self.addCleanup(override.disable)
        private_document_storage.cache_clear()
        self.addCleanup(private_document_storage.cache_clear)

        self.client = APIClient()
        self.user = User.objects.create_user(
            username='ramesh', email='ramesh@shop.com', phone_number='+919876500001',
            password='Password@123', user_type='retailer', first_name='Ramesh',
        )
        self.profile = RetailerProfile.objects.create(
            user=self.user, shop_name="Ramesh's Shop", address_line1='', city='', state='',
            pincode='000000', verification_status='pending', is_verified=False, is_active=False,
        )
        self.admin = User.objects.create_user(
            username='admin', email='admin@ordereasy.in', password='AdminPassword@123',
        )

    def complete_profile(self):
        self.user.is_phone_verified = True
        self.user.save(update_fields=['is_phone_verified'])
        p = self.profile
        p.shop_name = 'Ramesh Kirana Store'
        p.shop_image = SimpleUploadedFile('front.png', png_bytes(), content_type='image/png')
        p.address_line1 = '12 Main Market'
        p.city = 'Jaipur'
        p.state = 'Rajasthan'
        p.pincode = '302001'
        p.latitude = Decimal('26.91240000')
        p.longitude = Decimal('75.78730000')
        p.proof_type = 'gst'
        p.gst_number = VALID_GSTIN
        p.save()
        RetailerVerificationDocument.objects.create(
            retailer=p, kind='owner_id',
            file=SimpleUploadedFile('id.png', png_bytes(), content_type='image/png'),
            content_type='image/png',
        )

    def results(self):
        return {r['key']: r['result'] for r in run_checks(self.profile)}


class ContentRuleTests(TestCase):
    def test_banned_restricted_and_clean(self):
        self.assertEqual(check_text('Kingfisher Beer Shop')[0], 'banned')
        self.assertEqual(check_text('Gold Flake cigarettes')[0], 'banned')
        self.assertEqual(check_text('Paracetamol tablet')[0], 'restricted')
        self.assertEqual(check_text('Call 9876543210 now')[0], 'fail')
        self.assertEqual(check_text('Best!!!! deals')[0], 'fail')
        self.assertEqual(check_text('Sharma Kirana Store')[0], 'pass')
        # Word boundaries: "Gunjan" and "Rumali roti" are fine.
        self.assertEqual(check_text('Gunjan General Store')[0], 'pass')
        self.assertEqual(check_text('Rumali Roti Corner')[0], 'pass')

    def test_gstin_checksum(self):
        self.assertTrue(gstin_checksum_ok(VALID_GSTIN))
        self.assertFalse(gstin_checksum_ok(VALID_GSTIN[:-1] + 'W'))
        self.assertFalse(gstin_checksum_ok('22AAAAA0000A1Z5'[:-1]))


class AutomatedCheckTests(_Base):
    def test_fresh_signup_fails_blocking_checks(self):
        r = self.results()
        for key in ('phone', 'shop_name', 'shop_photo', 'address', 'proof', 'owner_id'):
            self.assertEqual(r[key], 'fail', key)
        self.assertEqual(r['duplicates'], 'pass')

    def test_complete_profile_has_no_failures(self):
        self.complete_profile()
        r = self.results()
        self.assertNotIn('fail', r.values())
        self.assertEqual(r['proof'], 'manual')
        self.assertEqual(r['owner_id'], 'manual')

    def test_bad_gstin_checksum_fails(self):
        self.complete_profile()
        self.profile.gst_number = VALID_GSTIN[:-1] + 'W'
        self.profile.save()
        self.assertEqual(self.results()['proof'], 'fail')

    def test_pan_mismatch_flags(self):
        self.complete_profile()
        self.profile.pan_number = 'ABCDE1234F'
        self.profile.save()
        self.assertEqual(self.results()['proof'], 'flag')

    def test_duplicate_gstin_flags(self):
        self.complete_profile()
        other_user = User.objects.create_user(username='other', password='x', user_type='retailer')
        RetailerProfile.objects.create(user=other_user, shop_name='Other', address_line1='a', city='c',
                                       state='s', pincode='302002', gst_number=VALID_GSTIN)
        self.assertEqual(self.results()['duplicates'], 'flag')

    def test_fssai_needs_number_and_document(self):
        self.complete_profile()
        self.profile.proof_type = 'fssai'
        self.profile.gst_number = ''
        self.profile.save()
        self.assertEqual(self.results()['proof'], 'fail')
        self.profile.proof_number = '12345678901234'
        self.profile.save()
        self.assertEqual(self.results()['proof'], 'fail')  # still no photo
        RetailerVerificationDocument.objects.create(
            retailer=self.profile, kind='proof',
            file=SimpleUploadedFile('f.png', png_bytes()), content_type='image/png')
        self.assertEqual(self.results()['proof'], 'manual')

    def test_banned_shop_name_fails(self):
        self.complete_profile()
        self.profile.shop_name = 'Daru Wine Shop'
        self.profile.save()
        self.assertEqual(self.results()['shop_name'], 'fail')


class RetailerEndpointTests(_Base):
    def test_status_and_submit_blocked_until_complete(self):
        self.client.force_authenticate(self.user)
        res = self.client.get('/api/retailer/verification/')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data['ready'])
        self.assertEqual([s['key'] for s in res.data['steps']], ['phone', 'shop', 'address', 'proof', 'owner_id'])

        res = self.client.post('/api/retailer/verification/submit/')
        self.assertEqual(res.status_code, 400)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.verification_submitted_at)

        self.complete_profile()
        res = self.client.post('/api/retailer/verification/submit/')
        self.assertEqual(res.status_code, 200, res.data)
        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.verification_submitted_at)
        self.assertEqual(self.profile.verification_status, 'pending')
        self.assertTrue(VerificationEvent.objects.filter(retailer=self.profile, action='submit').exists())

    def test_document_upload_is_private_and_validated(self):
        self.client.force_authenticate(self.user)
        bad = SimpleUploadedFile('x.png', b'not an image', content_type='image/png')
        res = self.client.post('/api/retailer/verification/documents/', {'kind': 'owner_id', 'file': bad}, format='multipart')
        self.assertEqual(res.status_code, 400)

        good = SimpleUploadedFile('id.png', png_bytes(), content_type='image/png')
        res = self.client.post('/api/retailer/verification/documents/', {'kind': 'owner_id', 'file': good}, format='multipart')
        self.assertEqual(res.status_code, 201, res.data)
        doc = RetailerVerificationDocument.objects.get(retailer=self.profile, kind='owner_id')
        self.assertTrue(doc.file.path.startswith(self.tmp))  # not in public media

        # Second upload replaces the first.
        again = SimpleUploadedFile('id2.png', png_bytes(), content_type='image/png')
        self.client.post('/api/retailer/verification/documents/', {'kind': 'owner_id', 'file': again}, format='multipart')
        self.assertEqual(RetailerVerificationDocument.objects.filter(retailer=self.profile, kind='owner_id').count(), 1)

        # Retailer cannot read the admin endpoint; admin can.
        url = f'/api/retailer/admin/verifications/{self.profile.id}/documents/{RetailerVerificationDocument.objects.get(retailer=self.profile).id}/'
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_authenticate(self.admin)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'image/png')
        self.assertIn('no-store', res['Cache-Control'])

    def test_upload_limit_does_not_share_the_global_user_throttle_key(self):
        # The global per-user throttle records every request under its key;
        # sharing it made uploads fail after ~30 ordinary page loads.
        from rest_framework.test import APIRequestFactory, force_authenticate
        from rest_framework.request import Request
        from rest_framework.throttling import UserRateThrottle
        from retailers.verification_views import DocumentUploadThrottle
        raw = APIRequestFactory().post('/x')
        force_authenticate(raw, user=self.user)
        request = Request(raw)
        request.user = self.user
        self.assertNotEqual(
            DocumentUploadThrottle().get_cache_key(request, None),
            UserRateThrottle().get_cache_key(request, None),
        )

    def test_customer_user_has_no_checklist(self):
        customer = User.objects.create_user(username='cust', password='x', user_type='customer')
        self.client.force_authenticate(customer)
        self.assertEqual(self.client.get('/api/retailer/verification/').status_code, 404)

    def test_profile_change_after_approval_flags_review(self):
        self.complete_profile()
        self.client.force_authenticate(self.admin)
        self.client.post(f'/api/retailer/admin/verifications/{self.profile.id}/action/', {'action': 'approve'}, format='json')

        self.client.force_authenticate(self.user)
        res = self.client.patch('/api/retailer/profile/update/', {'shop_description': 'Fresh atta'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.verification_review_needed)

        res = self.client.patch('/api/retailer/profile/update/', {'shop_name': 'Ramesh Super Mart'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.verification_review_needed)
        self.assertEqual(self.profile.verification_status, 'approved')  # stays live
        ev = VerificationEvent.objects.get(retailer=self.profile, action='profile_changed')
        self.assertEqual(ev.details['changed']['shop_name']['to'], 'Ramesh Super Mart')

        self.client.force_authenticate(self.admin)
        res = self.client.get('/api/retailer/admin/verifications/?status=review_needed')
        self.assertEqual([r['id'] for r in res.data['results']], [self.profile.id])
        self.client.post(f'/api/retailer/admin/verifications/{self.profile.id}/action/', {'action': 'mark_reviewed'}, format='json')
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.verification_review_needed)


class AdminActionTests(_Base):
    def action(self, action, reason=None):
        self.client.force_authenticate(self.admin)
        body = {'action': action}
        if reason is not None:
            body['reason'] = reason
        return self.client.post(f'/api/retailer/admin/verifications/{self.profile.id}/action/', body, format='json')

    def test_request_changes_then_resubmit_then_approve(self):
        self.complete_profile()
        self.assertEqual(self.action('request_changes').status_code, 400)  # reason required
        res = self.action('request_changes', 'Photo is too dark.')
        self.assertEqual(res.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, 'needs_changes')
        self.assertEqual(self.profile.rejection_reason, 'Photo is too dark.')
        self.assertFalse(RetailerProfile.objects.public().filter(pk=self.profile.pk).exists())

        self.client.force_authenticate(self.user)
        res = self.client.get('/api/retailer/verification/')
        self.assertEqual(res.data['reason'], 'Photo is too dark.')
        self.assertEqual(self.client.post('/api/retailer/verification/submit/').status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, 'pending')

        self.assertEqual(self.action('approve').status_code, 200)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_active)
        self.assertTrue(RetailerProfile.objects.public().filter(pk=self.profile.pk).exists())
        actions = list(VerificationEvent.objects.filter(retailer=self.profile).order_by('id').values_list('action', flat=True))
        self.assertEqual(actions, ['request_changes', 'submit', 'approve'])

    def test_suspend_hides_and_reinstate_restores(self):
        self.action('approve')
        RetailerProfile.objects.filter(pk=self.profile.pk).update(is_active=True)
        self.assertEqual(self.action('suspend').status_code, 400)  # reason required
        self.assertEqual(self.action('suspend', 'Repeated misleading products').status_code, 200)
        self.assertFalse(RetailerProfile.objects.public().filter(pk=self.profile.pk).exists())
        self.assertEqual(self.action('reinstate').status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, 'approved')
        self.assertTrue(RetailerProfile.objects.public().filter(pk=self.profile.pk).exists())

    def test_invalid_transitions_are_refused(self):
        self.assertEqual(self.action('suspend', 'x').status_code, 400)  # pending cannot be suspended
        self.assertEqual(self.action('reinstate').status_code, 400)
        self.assertEqual(self.action('bogus').status_code, 400)
        self.action('reject', 'Fake shop')
        self.assertEqual(self.action('request_changes', 'x').status_code, 400)

    def test_submit_not_allowed_once_approved(self):
        self.complete_profile()
        self.action('approve')
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post('/api/retailer/verification/submit/').status_code, 400)

    def test_detail_has_checks_documents_and_events(self):
        self.complete_profile()
        self.action('request_changes', 'Need a clearer photo')
        self.client.force_authenticate(self.admin)
        res = self.client.get(f'/api/retailer/admin/verifications/{self.profile.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('checks', res.data)
        self.assertEqual(res.data['documents'][0]['kind'], 'owner_id')
        self.assertEqual(res.data['events'][0]['action'], 'request_changes')
        self.assertEqual(res.data['events'][0]['actor'], 'admin@ordereasy.in')

    def test_list_counts_and_submitted_first(self):
        other = User.objects.create_user(username='o2', password='x', user_type='retailer')
        other_profile = RetailerProfile.objects.create(user=other, shop_name='Later', address_line1='a', city='c',
                                                       state='s', pincode='302002')
        self.complete_profile()
        self.client.force_authenticate(self.user)
        self.client.post('/api/retailer/verification/submit/')
        self.client.force_authenticate(self.admin)
        res = self.client.get('/api/retailer/admin/verifications/?status=pending')
        ids = [r['id'] for r in res.data['results']]
        self.assertEqual(ids[0], self.profile.id)
        self.assertIn(other_profile.id, ids)
        self.assertIsNotNone(res.data['results'][0]['check_counts'])
        for key in ('pending', 'approved', 'rejected', 'needs_changes', 'suspended', 'review_needed', 'all'):
            self.assertIn(key, res.data['counts'])
