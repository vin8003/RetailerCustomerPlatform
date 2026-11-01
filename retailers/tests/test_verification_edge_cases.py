"""Positive, negative and regression tests for retailer verification
(docs/requirements/retailer-verification.md sections 3 and 9)."""
import os
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from authentication.models import User
from common.content_rules import check_text
from retailers.models import RetailerProfile, RetailerVerificationDocument, VerificationEvent
from retailers.tests.test_retailer_verification_flow import VALID_GSTIN, _Base, png_bytes
from retailers.verification import gstin_checksum_ok

ADMIN_ACTION_URL = '/api/retailer/admin/verifications/{}/action/'


class ContentRuleEdgeCaseTests(TestCase):
    def assertResult(self, text, expected, **kw):
        self.assertEqual(check_text(text, **kw)[0], expected, text)

    def test_clean_shop_and_product_names_pass(self):
        for text in ('Sharma Kirana Store', 'Aashirvaad Atta 5kg', 'Amul Taaza 1L', 'Shree Ganesh General Store'):
            self.assertResult(text, 'pass')

    def test_regression_words_inside_other_words_are_not_banned(self):
        # Whole-word matching: these contain a banned word as a substring only.
        for text in ('Rumali Roti', 'Beerbal Sweets', 'Gunny Bags', 'Winery Road Dairy', 'Spectrum Mobiles'):
            self.assertResult(text, 'pass')

    def test_each_banned_category(self):
        for text, category in (('Old Monk Rum', 'alcohol'), ('Gutka pouch', 'tobacco'),
                               ('Adult toys', 'adult'), ('Air pistol', 'weapons')):
            result, reason, cat = check_text(text)
            self.assertEqual((result, cat), ('banned', category), text)
            self.assertIn(category, reason)

    def test_banned_check_ignores_case(self):
        self.assertResult('KINGFISHER BEER', 'banned')

    def test_contact_spam_fails(self):
        for text in ('Call +91 98765 43210', 'Call 98765-43210 now', 'Order at www.cheap.in',
                     'Visit https://x.co', 'Chat wa.me/919876543210', 'Best deals!!!!', 'Sooooooper sale'):
            self.assertResult(text, 'fail')

    def test_regression_barcode_and_landline_digits_are_not_phones(self):
        self.assertResult('Parle G 8901063010016', 'pass')
        self.assertResult('Pack of 12345', 'pass')

    def test_abuse_fails(self):
        self.assertResult('Chutiya store', 'fail')

    def test_length_limits(self):
        self.assertResult('', 'fail')
        self.assertResult('  ab  ', 'fail')
        self.assertResult('abc', 'pass')
        self.assertResult('ab' * 30, 'pass')
        self.assertResult('ab' * 30 + 'c', 'fail')
        self.assertResult('abc ' * 125, 'pass', max_len=None)

    def test_restricted_is_not_banned(self):
        result, reason, category = check_text('Rat poison 100g')
        self.assertEqual((result, category), ('restricted', 'pesticide'))
        self.assertIn('admin approval', reason)

    def test_gstin_checksum_positive_and_negative(self):
        self.assertTrue(gstin_checksum_ok(VALID_GSTIN))
        self.assertTrue(gstin_checksum_ok(VALID_GSTIN.lower()))
        for bad in ('', None, VALID_GSTIN[:-1], VALID_GSTIN + 'A', '27AAPFU0939F1YV'):
            self.assertFalse(gstin_checksum_ok(bad), bad)
        wrong_last = [VALID_GSTIN[:-1] + c for c in '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ' if c != VALID_GSTIN[-1]]
        self.assertFalse(any(gstin_checksum_ok(g) for g in wrong_last))


class AutomatedCheckEdgeCaseTests(_Base):
    def test_zero_map_pin_and_bad_pincode_fail_the_address(self):
        self.complete_profile()
        RetailerProfile.objects.filter(pk=self.profile.pk).update(latitude=0, longitude=0, pincode='012345')
        self.profile.refresh_from_db()
        row = next(r for r in __import__('retailers.verification', fromlist=['run_checks']).run_checks(self.profile)
                   if r['key'] == 'address')
        self.assertEqual(row['result'], 'fail')
        self.assertIn('map pin', row['detail'])
        self.assertIn('valid pincode', row['detail'])

    def test_placeholder_shop_name_fails(self):
        self.complete_profile()
        RetailerProfile.objects.filter(pk=self.profile.pk).update(shop_name="Ramesh's Shop")
        self.profile.refresh_from_db()
        self.assertEqual(self.results()['shop_name'], 'fail')

    def test_restricted_shop_name_goes_to_admin_not_blocked(self):
        self.complete_profile()
        RetailerProfile.objects.filter(pk=self.profile.pk).update(shop_name='Ramesh Medicine Centre')
        self.profile.refresh_from_db()
        self.assertEqual(self.results()['shop_name'], 'manual')

    def test_shop_board_proof_needs_only_the_photo(self):
        self.complete_profile()
        RetailerProfile.objects.filter(pk=self.profile.pk).update(proof_type='board', gst_number='')
        self.profile.refresh_from_db()
        self.assertEqual(self.results()['proof'], 'fail')
        RetailerVerificationDocument.objects.create(
            retailer=self.profile, kind='proof', content_type='image/png',
            file=SimpleUploadedFile('board.png', png_bytes(), content_type='image/png'),
        )
        self.assertEqual(self.results()['proof'], 'manual')

    def test_no_proof_chosen_fails(self):
        self.complete_profile()
        RetailerProfile.objects.filter(pk=self.profile.pk).update(proof_type='', gst_number='')
        self.profile.refresh_from_db()
        self.assertEqual(self.results()['proof'], 'fail')

    def test_missing_owner_id_blocks_submit(self):
        self.complete_profile()
        RetailerVerificationDocument.objects.filter(retailer=self.profile, kind='owner_id').delete()
        self.client.force_authenticate(self.user)
        res = self.client.post('/api/retailer/verification/submit/')
        self.assertEqual(res.status_code, 400)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.verification_submitted_at)


class DocumentUploadEdgeCaseTests(_Base):
    URL = '/api/retailer/verification/documents/'

    def upload(self, data, name='doc.png', kind='owner_id', content_type='image/png'):
        self.client.force_authenticate(self.user)
        return self.client.post(self.URL, {'kind': kind, 'file': SimpleUploadedFile(name, data, content_type=content_type)},
                                format='multipart')

    def test_pdf_is_accepted(self):
        res = self.upload(b'%PDF-1.4\n%fake\n', name='gst.pdf', kind='proof', content_type='application/pdf')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(RetailerVerificationDocument.objects.get(retailer=self.profile).content_type, 'application/pdf')

    def test_negative_inputs_are_refused(self):
        self.assertEqual(self.upload(png_bytes(), kind='passport').status_code, 400)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(self.URL, {'kind': 'owner_id'}, format='multipart').status_code, 400)
        # Content type is taken from the bytes, not the header.
        self.assertEqual(self.upload(b'MZ\x90\x00 not an image', name='id.png').status_code, 400)
        self.assertEqual(self.upload(b'RIFF\x00\x00\x00\x00WAVEfmt ', name='id.webp', content_type='image/webp').status_code, 400)
        self.assertEqual(self.upload(b'<svg onload=alert(1)>', name='id.svg', content_type='image/svg+xml').status_code, 400)
        big = b'\x89PNG' + b'0' * (5 * 1024 * 1024)
        self.assertEqual(self.upload(big).status_code, 400)
        self.assertFalse(RetailerVerificationDocument.objects.exists())

    def test_reupload_replaces_and_deletes_the_old_file(self):
        self.assertEqual(self.upload(png_bytes()).status_code, 201)
        old = RetailerVerificationDocument.objects.get(retailer=self.profile)
        old_path = old.file.path
        self.assertTrue(os.path.exists(old_path))
        self.assertEqual(self.upload(png_bytes(), name='id2.png').status_code, 201)
        self.assertEqual(RetailerVerificationDocument.objects.filter(retailer=self.profile, kind='owner_id').count(), 1)
        self.assertFalse(os.path.exists(old_path))

    def test_anonymous_and_customer_cannot_use_retailer_endpoints(self):
        self.client.force_authenticate(None)
        for url in ('/api/retailer/verification/', '/api/retailer/verification/submit/', self.URL):
            res = self.client.post(url) if url != '/api/retailer/verification/' else self.client.get(url)
            self.assertIn(res.status_code, (401, 403), url)
        customer = User.objects.create_user(username='cust', password='x', user_type='customer')
        self.client.force_authenticate(customer)
        self.assertEqual(self.client.post('/api/retailer/verification/submit/').status_code, 404)


class AdminDocumentAccessTests(_Base):
    def setUp(self):
        super().setUp()
        self.doc = RetailerVerificationDocument.objects.create(
            retailer=self.profile, kind='owner_id', content_type='image/png',
            file=SimpleUploadedFile('id.png', png_bytes(), content_type='image/png'),
        )
        self.url = f'/api/retailer/admin/verifications/{self.profile.id}/documents/{self.doc.id}/'

    def test_admin_downloads_with_no_store(self):
        self.client.force_authenticate(self.admin)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(b''.join(res.streaming_content), png_bytes())
        self.assertEqual(res['Cache-Control'], 'private, no-store')
        self.assertEqual(res['Content-Type'], 'image/png')

    def test_owner_and_customers_cannot_download(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_document_of_another_shop_is_404(self):
        other_user = User.objects.create_user(username='other', password='x', user_type='retailer')
        other = RetailerProfile.objects.create(user=other_user, shop_name='Other', pincode='302001')
        self.client.force_authenticate(self.admin)
        res = self.client.get(f'/api/retailer/admin/verifications/{other.id}/documents/{self.doc.id}/')
        self.assertEqual(res.status_code, 404)

    def test_regression_document_never_lands_in_public_media(self):
        from django.conf import settings
        self.assertTrue(os.path.abspath(self.doc.file.path).startswith(os.path.abspath(settings.PRIVATE_MEDIA_ROOT)))
        self.assertIsNone(self.doc.file.storage.base_url)


class AdminActionEdgeCaseTests(_Base):
    def act(self, action, reason=None, profile=None):
        self.client.force_authenticate(self.admin)
        body = {'action': action}
        if reason is not None:
            body['reason'] = reason
        return self.client.post(ADMIN_ACTION_URL.format((profile or self.profile).id), body, format='json')

    def status(self):
        self.profile.refresh_from_db()
        return self.profile.verification_status

    def test_reasons_required_where_the_retailer_must_be_told_why(self):
        self.assertEqual(self.act('request_changes').status_code, 400)
        self.assertEqual(self.act('request_changes', '   ').status_code, 400)
        self.assertEqual(self.status(), 'pending')
        self.act('approve')
        self.assertEqual(self.act('suspend').status_code, 400)
        self.assertEqual(self.status(), 'approved')

    def test_reject_uses_default_reason_and_switches_shop_off(self):
        res = self.act('reject')
        self.assertEqual(res.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.rejection_reason, 'Verification rejected by administrator.')
        self.assertFalse(self.profile.is_active)
        self.assertFalse(self.profile.is_verified)

    def test_first_approval_activates_and_lists_the_shop(self):
        self.assertEqual(self.act('approve').status_code, 200)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_active and self.profile.is_verified)
        self.assertTrue(RetailerProfile.objects.public().filter(pk=self.profile.pk).exists())

    def test_regression_reinstate_keeps_the_retailers_own_off_switch(self):
        self.act('approve')
        RetailerProfile.objects.filter(pk=self.profile.pk).update(is_active=False)
        self.act('suspend', 'Fake listings')
        self.assertEqual(self.act('reinstate').status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, 'approved')
        self.assertFalse(self.profile.is_active)

    def test_mark_reviewed_clears_the_flag_and_keeps_status(self):
        self.act('approve')
        RetailerProfile.objects.filter(pk=self.profile.pk).update(verification_review_needed=True)
        self.assertEqual(self.act('mark_reviewed').status_code, 200)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.verification_review_needed)
        self.assertEqual(self.profile.verification_status, 'approved')

    def test_invalid_action_and_unknown_shop(self):
        self.assertEqual(self.act('delete').status_code, 400)
        self.client.force_authenticate(self.admin)
        res = self.client.post(ADMIN_ACTION_URL.format(999999), {'action': 'approve'}, format='json')
        self.assertEqual(res.status_code, 404)

    def test_non_admins_cannot_act(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(ADMIN_ACTION_URL.format(self.profile.id), {'action': 'approve'}, format='json')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.status(), 'pending')
        self.assertEqual(self.client.get(f'/api/retailer/admin/verifications/{self.profile.id}/').status_code, 403)

    def test_every_action_is_audited_with_actor(self):
        self.act('request_changes', 'Photo is blurry')
        self.act('approve')
        self.act('suspend', 'Fake brand')
        self.act('reinstate')
        events = list(VerificationEvent.objects.filter(retailer=self.profile).order_by('id')
                      .values_list('action', 'from_status', 'to_status', 'actor_id'))
        self.assertEqual(events, [
            ('request_changes', 'pending', 'needs_changes', self.admin.id),
            ('approve', 'needs_changes', 'approved', self.admin.id),
            ('suspend', 'approved', 'suspended', self.admin.id),
            ('reinstate', 'suspended', 'approved', self.admin.id),
        ])

    def test_rejected_shop_cannot_resubmit(self):
        self.complete_profile()
        self.act('reject')
        self.client.force_authenticate(self.user)
        res = self.client.post('/api/retailer/verification/submit/')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.status(), 'rejected')


class ProfileEditTests(_Base):
    """Shop name checks on the retailer's own profile edit (review fix)."""
    URL = '/api/retailer/profile/update/'

    def setUp(self):
        super().setUp()
        self.complete_profile()
        RetailerProfile.objects.filter(pk=self.profile.pk).update(
            verification_status='approved', is_verified=True, is_active=True)
        self.client.force_authenticate(self.user)

    def edit(self, **data):
        return self.client.patch(self.URL, data, format='json')

    def test_clean_rename_saves_and_flags_review(self):
        res = self.edit(shop_name='Ramesh Super Mart')
        self.assertEqual(res.status_code, 200, res.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.shop_name, 'Ramesh Super Mart')
        self.assertTrue(self.profile.verification_review_needed)
        self.assertEqual(self.profile.verification_status, 'approved')

    def test_banned_abusive_or_contact_names_are_refused(self):
        for name in ('Ramesh Wine Shop', 'Chutiya Store', 'Call 9876543210', 'www.ramesh.in', 'ab'):
            res = self.edit(shop_name=name)
            self.assertEqual(res.status_code, 400, name)
            self.assertIn('shop_name', str(res.data))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.shop_name, 'Ramesh Kirana Store')
        self.assertFalse(VerificationEvent.objects.filter(action='profile_changed').exists())

    def test_regression_existing_name_does_not_block_other_edits(self):
        # A legacy name that would fail today must not stop the shop saving other fields.
        RetailerProfile.objects.filter(pk=self.profile.pk).update(shop_name='Wine & Dine Kirana')
        res = self.edit(shop_name='Wine & Dine Kirana', shop_description='Open 7 to 10')
        self.assertEqual(res.status_code, 200, res.data)

    def test_restricted_name_is_allowed_for_admin_review(self):
        res = self.edit(shop_name='Ramesh Medicine Centre')
        self.assertEqual(res.status_code, 200, res.data)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.verification_review_needed)

    def test_non_sensitive_edit_does_not_flag(self):
        res = self.edit(shop_description='Fresh vegetables daily')
        self.assertEqual(res.status_code, 200, res.data)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.verification_review_needed)
