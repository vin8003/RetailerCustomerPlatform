"""Product text moderation, customer reports and strikes
(docs/requirements/retailer-verification.md sections 4 and 5)."""
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from authentication.models import User
from products.models import MasterProduct, Product, ProductCategory
from retailers.models import CustomerReport, RetailerProfile, RetailerStrike, VerificationEvent


def make_shop(username='shopowner'):
    user = User.objects.create_user(username=username, email=f'{username}@t.com', password='x', user_type='retailer')
    profile = RetailerProfile.objects.create(
        user=user, shop_name='Sharma Kirana', address_line1='1 Main', city='Jaipur', state='RJ',
        pincode='302001', is_active=True, is_verified=True, verification_status='approved',
    )
    return user, profile


def make_product(shop, name, **kw):
    category = ProductCategory.objects.get_or_create(name='Grocery', retailer=shop)[0]
    fields = dict(retailer=shop, category=category, name=name, price=Decimal('20.00'), quantity=Decimal('5'),
                  track_inventory=True, is_active=True, is_available=True, unit='piece')
    fields.update(kw)
    return Product.objects.create(**fields)


class TextModerationTests(TestCase):
    def setUp(self):
        _, self.shop = make_shop()

    def test_clean_product_is_live(self):
        p = make_product(self.shop, 'Aashirvaad Atta 5kg')
        self.assertEqual(p.moderation_status, 'ok')

    def test_banned_words_hide_the_product(self):
        for name in ('Kingfisher Beer 650ml', 'Gold Flake Cigarettes', 'Toy gun for sale'):
            p = make_product(self.shop, name)
            self.assertEqual(p.moderation_status, 'hidden', name)
            self.assertTrue(p.moderation_reason.startswith('Auto: Banned category'))

    def test_restricted_goes_to_review(self):
        p = make_product(self.shop, 'Paracetamol 500 tablets')
        self.assertEqual(p.moderation_status, 'pending_review')

    def test_phone_number_in_name_is_hidden_but_barcode_digits_are_not(self):
        self.assertEqual(make_product(self.shop, 'Call 9876543210 for atta').moderation_status, 'hidden')
        self.assertEqual(make_product(self.shop, 'Parle G 8901063010016').moderation_status, 'ok')

    def test_fixing_the_name_clears_an_auto_hold(self):
        p = make_product(self.shop, 'Old Monk Rum')
        self.assertEqual(p.moderation_status, 'hidden')
        p.name = 'Old Monk Cake'
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.moderation_status, 'ok')

    def test_stock_updates_do_not_reevaluate(self):
        p = make_product(self.shop, 'Sugar 1kg')
        Product.objects.filter(pk=p.pk).update(moderation_status='hidden', moderation_reason='Admin decision')
        p.refresh_from_db()
        p.quantity = Decimal('9')
        p.save(update_fields=['quantity'])
        p.refresh_from_db()
        self.assertEqual(p.moderation_status, 'hidden')
        p.save()  # full save, text unchanged
        p.refresh_from_db()
        self.assertEqual(p.moderation_status, 'hidden')

    def test_admin_hold_is_not_cleared_by_an_edit(self):
        p = make_product(self.shop, 'Sugar 1kg')
        Product.objects.filter(pk=p.pk).update(moderation_status='removed', moderation_reason='Fake brand')
        p.refresh_from_db()
        p.name = 'Sugar 1 kg'
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.moderation_status, 'removed')

    def test_master_catalog_name_is_trusted(self):
        master = MasterProduct.objects.create(barcode='111', name='Bira 91 Blonde Beer')
        p = make_product(self.shop, 'Bira 91 Blonde Beer', master_product=master)
        self.assertEqual(p.moderation_status, 'ok')


@override_settings(ADMIN_EMAILS=['admin@ordereasy.in'])
class CustomerVisibilityAndReportTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner, self.shop = make_shop()
        self.product = make_product(self.shop, 'Super Herbal Gold')
        self.admin = User.objects.create_user(username='admin', email='admin@ordereasy.in', password='x')
        self.customers = [
            User.objects.create_user(username=f'c{i}', email=f'c{i}@t.com', password='x', user_type='customer')
            for i in range(4)
        ]

    def report(self, user, product=True, reason='misleading'):
        self.client.force_authenticate(user)
        body = {'reason': reason, 'text': 'Claims to cure everything'}
        if product:
            body['product_id'] = self.product.id
        return self.client.post(f'/api/retailer/{self.shop.id}/report/', body, format='json')

    def test_hidden_products_are_invisible_to_customers(self):
        url_list = f'/api/products/retailer/{self.shop.id}/'
        url_detail = f'/api/products/retailer/{self.shop.id}/{self.product.id}/'
        self.client.force_authenticate(self.customers[0])
        self.assertEqual(self.client.get(url_detail).status_code, 200)
        self.client.force_authenticate(self.customers[1])
        ok = self.client.post('/api/cart/add/', {'product_id': self.product.id, 'quantity': 1}, format='json')
        self.assertIn(ok.status_code, (200, 201), ok.data)
        self.client.force_authenticate(self.customers[0])
        Product.objects.filter(pk=self.product.pk).update(moderation_status='hidden')
        self.assertEqual(self.client.get(url_detail).status_code, 404)
        res = self.client.get(url_list)
        names = [p['name'] for p in (res.data.get('results', res.data) if isinstance(res.data, dict) else res.data)]
        self.assertNotIn('Super Herbal Gold', names)
        res = self.client.post('/api/cart/add/', {'product_id': self.product.id, 'quantity': 1}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_three_distinct_reporters_hide_the_product(self):
        self.assertEqual(self.report(self.customers[0]).status_code, 201)
        self.assertEqual(self.report(self.customers[0]).status_code, 200)  # duplicate ignored
        self.report(self.customers[1])
        self.product.refresh_from_db()
        self.assertEqual(self.product.moderation_status, 'ok')
        self.report(self.customers[2])
        self.product.refresh_from_db()
        self.assertEqual(self.product.moderation_status, 'pending_review')
        self.assertIn('reported by 3 customers', self.product.moderation_reason)

    def test_owner_cannot_report_own_shop_and_bad_input_is_refused(self):
        self.client.force_authenticate(self.owner)
        res = self.client.post(f'/api/retailer/{self.shop.id}/report/', {'reason': 'misleading'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.report(self.customers[0], reason='bogus').status_code, 400)
        self.client.force_authenticate(self.customers[0])
        res = self.client.post(f'/api/retailer/{self.shop.id}/report/', {'reason': 'other', 'product_id': 999999}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_cannot_report_unlisted_shop(self):
        RetailerProfile.objects.filter(pk=self.shop.pk).update(verification_status='pending', is_verified=False)
        self.assertEqual(self.report(self.customers[0]).status_code, 404)

    def test_dismiss_restores_a_report_hold(self):
        for c in self.customers[:3]:
            self.report(c)
        self.client.force_authenticate(self.admin)
        res = self.client.get('/api/retailer/admin/reports/')
        self.assertEqual(res.status_code, 200)
        group = res.data['results'][0]
        self.assertEqual((group['product_id'], group['reporters']), (self.product.id, 3))
        res = self.client.post('/api/retailer/admin/reports/action/', {
            'retailer_id': self.shop.id, 'product_id': self.product.id, 'action': 'dismiss'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['reports_closed'], 3)
        self.product.refresh_from_db()
        self.assertEqual(self.product.moderation_status, 'ok')
        self.assertFalse(CustomerReport.objects.filter(status='open').exists())

    def test_three_strikes_suspend_the_shop(self):
        self.client.force_authenticate(self.admin)
        self.report(self.customers[0])
        self.client.force_authenticate(self.admin)
        url = '/api/retailer/admin/reports/action/'
        self.assertEqual(self.client.post(url, {'retailer_id': self.shop.id, 'product_id': self.product.id,
                                                 'action': 'strike'}, format='json').status_code, 400)  # reason needed
        res = self.client.post(url, {'retailer_id': self.shop.id, 'product_id': self.product.id,
                                     'action': 'strike', 'reason': 'Misleading health claims'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.moderation_status, 'removed')
        for i in range(2):
            res = self.client.post(url, {'retailer_id': self.shop.id, 'action': 'strike', 'reason': f'Violation {i}'}, format='json')
        self.assertTrue(res.data['suspended'])
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.verification_status, 'suspended')
        self.assertFalse(RetailerProfile.objects.public().filter(pk=self.shop.pk).exists())
        self.assertEqual(RetailerStrike.objects.filter(retailer=self.shop).count(), 3)
        self.assertTrue(VerificationEvent.objects.filter(retailer=self.shop, action='suspend').exists())

    def test_five_shop_reporters_flag_the_shop(self):
        extra = [User.objects.create_user(username=f'x{i}', password='x', user_type='customer') for i in range(5)]
        for user in extra:
            self.report(user, product=False, reason='not_delivered')
        self.shop.refresh_from_db()
        self.assertTrue(self.shop.verification_review_needed)
        self.assertTrue(VerificationEvent.objects.filter(retailer=self.shop, action='reports_threshold').exists())

    def test_admin_product_review_queue_and_approve(self):
        p = make_product(self.shop, 'Rum Balls (eggless cake)')
        self.assertEqual(p.moderation_status, 'hidden')  # false positive
        self.client.force_authenticate(self.admin)
        res = self.client.get('/api/retailer/admin/products/review/?status=hidden')
        self.assertEqual([r['id'] for r in res.data['results']], [p.id])
        self.assertEqual(res.data['counts']['hidden'], 1)
        self.assertEqual(self.client.post(f'/api/retailer/admin/products/{p.id}/moderate/', {'action': 'hide'}, format='json').status_code, 400)
        res = self.client.post(f'/api/retailer/admin/products/{p.id}/moderate/', {'action': 'approve'}, format='json')
        self.assertEqual(res.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.moderation_status, 'ok')
        # Saving the same text again does not re-hide it.
        p.description = ''
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.moderation_status, 'ok')

    def test_retailer_sees_moderation_fields(self):
        Product.objects.filter(pk=self.product.pk).update(moderation_status='hidden', moderation_reason='Auto: x')
        self.client.force_authenticate(self.owner)
        res = self.client.get('/api/products/')
        rows = res.data.get('results', res.data)
        row = next(r for r in rows if r['id'] == self.product.id)
        self.assertEqual(row['moderation_status'], 'hidden')
        self.assertEqual(row['moderation_reason'], 'Auto: x')

    def test_non_admin_cannot_use_admin_endpoints(self):
        self.client.force_authenticate(self.customers[0])
        self.assertEqual(self.client.get('/api/retailer/admin/reports/').status_code, 403)
        self.assertEqual(self.client.get('/api/retailer/admin/products/review/').status_code, 403)
