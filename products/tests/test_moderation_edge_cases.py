"""Positive, negative and regression tests for product moderation, customer
reports and strikes (docs/requirements/retailer-verification.md sections 4, 5, 9)."""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from authentication.models import User
from customers.models import CustomerWishlist
from products.models import Product, ProductCategory
from products.tests.test_moderation_reports import make_product, make_shop
from retailers.models import CustomerReport, RetailerProfile, RetailerStrike, VerificationEvent
from retailers.reports import handle_reports

REPORT_ACTION_URL = '/api/retailer/admin/reports/action/'


class ProductTextEdgeCaseTests(TestCase):
    def setUp(self):
        _, self.shop = make_shop()

    def test_banned_word_in_description_hides(self):
        p = make_product(self.shop, 'Party Pack', description='Comes with free cigarettes')
        self.assertEqual(p.moderation_status, 'hidden')
        self.assertIn('in the description', p.moderation_reason)

    def test_restricted_word_in_description_goes_to_review(self):
        p = make_product(self.shop, 'Cold relief', description='Cough syrup 100ml')
        self.assertEqual(p.moderation_status, 'pending_review')

    def test_phone_in_description_hides(self):
        p = make_product(self.shop, 'Atta 5kg', description='WhatsApp 9876543210 for bulk')
        self.assertEqual(p.moderation_status, 'hidden')

    def test_long_clean_description_is_fine(self):
        p = make_product(self.shop, 'Atta 5kg', description='Stone ground whole wheat flour. ' * 40)
        self.assertEqual(p.moderation_status, 'ok')

    def test_partial_save_with_name_is_checked(self):
        p = make_product(self.shop, 'Sugar 1kg')
        p.name = 'Sugar and beer combo'
        p.save(update_fields=['name'])
        p.refresh_from_db()
        self.assertEqual(p.moderation_status, 'hidden')

    def test_regression_queryset_update_is_not_moderated(self):
        # Documented limit: .update() skips save(); only text-free columns use it.
        p = make_product(self.shop, 'Sugar 1kg')
        Product.objects.filter(pk=p.pk).update(quantity=Decimal('1'))
        p.refresh_from_db()
        self.assertEqual(p.moderation_status, 'ok')

    def test_admin_approved_text_is_rechecked_once_changed(self):
        p = make_product(self.shop, 'Rum Balls cake')
        client = APIClient()
        admin = User.objects.create_user(username='adm', email='admin@ordereasy.in', password='x')
        with override_settings(ADMIN_EMAILS=['admin@ordereasy.in']):
            client.force_authenticate(admin)
            client.post(f'/api/retailer/admin/products/{p.id}/moderate/', {'action': 'approve'}, format='json')
        p.refresh_from_db()
        self.assertEqual(p.moderation_status, 'ok')
        p.name = 'Rum Balls cake and vodka'
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.moderation_status, 'hidden')
        p.name = 'Rum Balls cake'
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.moderation_status, 'ok')

    def test_customer_visible_property(self):
        p = make_product(self.shop, 'Sugar 1kg')
        self.assertTrue(p.customer_visible)
        for field, value in (('moderation_status', 'pending_review'), ('moderation_status', 'removed'),
                             ('is_active', False), ('is_available', False)):
            q = Product.objects.get(pk=p.pk)
            setattr(q, field, value)
            self.assertFalse(q.customer_visible, field)


@override_settings(ADMIN_EMAILS=['admin@ordereasy.in'])
class CustomerPathRegressionTests(TestCase):
    """Every customer-facing path must skip held products (review fixes)."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner, self.shop = make_shop()
        self.customer = User.objects.create_user(username='cust', email='c@t.com', password='x', user_type='customer')
        self.cat_live = ProductCategory.objects.create(name='Snacks', retailer=self.shop)
        self.cat_held = ProductCategory.objects.create(name='Party', retailer=self.shop)
        self.live = make_product(self.shop, 'Lays Classic 50g', category=self.cat_live, product_group='Lays')
        self.sibling = make_product(self.shop, 'Lays Classic 100g', category=self.cat_live, product_group='Lays')
        self.held = make_product(self.shop, 'Lays Party Pack', category=self.cat_held, product_group='Lays')
        Product.objects.filter(pk=self.held.pk).update(moderation_status='hidden', moderation_reason='Fake brand')
        self.client.force_authenticate(self.customer)

    def ids(self, res):
        rows = res.data.get('results', res.data) if isinstance(res.data, dict) else res.data
        return {r['id'] for r in rows}

    def test_public_listing_and_search_skip_held(self):
        res = self.client.get(f'/api/products/retailer/{self.shop.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(self.held.id, self.ids(res))
        self.assertIn(self.live.id, self.ids(res))
        res = self.client.get(f'/api/products/retailer/{self.shop.id}/search/', {'search': 'Lays'})
        self.assertNotIn(self.held.id, self.ids(res))

    def test_detail_variants_skip_held_sibling(self):
        res = self.client.get(f'/api/products/retailer/{self.shop.id}/{self.live.id}/')
        self.assertEqual(res.status_code, 200)
        variant_ids = {v['id'] for v in res.data['group_variants']}
        self.assertIn(self.sibling.id, variant_ids)
        self.assertNotIn(self.held.id, variant_ids)

    def test_frequently_bought_together_skips_held(self):
        res = self.client.get(f'/api/products/retailer/{self.shop.id}/frequently-bought-together/',
                              {'product_ids': str(self.live.id)})
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(self.held.id, self.ids(res))

    def test_category_counts_and_groups_skip_held(self):
        res = self.client.get(f'/api/products/retailer/{self.shop.id}/categories/')
        self.assertEqual(res.status_code, 200)
        counts = {row['id']: row.get('product_count') for row in res.data}
        self.assertNotIn(self.cat_held.id, counts)
        self.assertEqual(counts.get(self.cat_live.id), 2)
        Product.objects.filter(pk=self.sibling.pk).update(product_group='Kurkure', moderation_status='hidden')
        res = self.client.get(f'/api/products/retailer/{self.shop.id}/categories/{self.cat_live.id}/groups/')
        self.assertEqual(res.data, ['Lays'])

    def test_wishlist_hides_and_refuses_held(self):
        CustomerWishlist.objects.create(customer=self.customer, product=self.held)
        CustomerWishlist.objects.create(customer=self.customer, product=self.live)
        res = self.client.get('/api/customer/wishlist/')
        self.assertEqual(res.status_code, 200)
        rows = res.data.get('results', res.data)
        self.assertEqual([r['product'] for r in rows], [self.live.id])
        res = self.client.post('/api/customer/wishlist/add/', {'product': self.sibling.id}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        Product.objects.filter(pk=self.sibling.pk).update(moderation_status='pending_review')
        CustomerWishlist.objects.filter(product=self.sibling).delete()
        res = self.client.post('/api/customer/wishlist/add/', {'product': self.sibling.id}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_held_product_in_cart_blocks_checkout_validation(self):
        res = self.client.post('/api/cart/add/', {'product_id': self.live.id, 'quantity': 1}, format='json')
        self.assertIn(res.status_code, (200, 201), res.data)
        Product.objects.filter(pk=self.live.pk).update(moderation_status='removed')
        res = self.client.post('/api/cart/validate/', {'retailer_id': self.shop.id}, format='json')
        self.assertIn('no longer available', str(res.data))

    def test_retailer_own_listing_still_shows_held(self):
        self.client.force_authenticate(self.owner)
        res = self.client.get('/api/products/')
        self.assertIn(self.held.id, self.ids(res))


@override_settings(ADMIN_EMAILS=['admin@ordereasy.in'])
class ReviewOnlyThresholdTests(TestCase):
    """Decided 2026-10-31: reports and strikes never hide or suspend on their own."""

    def setUp(self):
        self.client = APIClient()
        self.owner, self.shop = make_shop()
        self.product = make_product(self.shop, 'Super Herbal Gold')
        self.admin = User.objects.create_user(username='admin', email='admin@ordereasy.in', password='x')
        self.customers = [User.objects.create_user(username=f'c{i}', password='x', user_type='customer')
                          for i in range(10)]

    def report(self, user, product=True, reason='misleading', text=''):
        self.client.force_authenticate(user)
        body = {'reason': reason, 'text': text}
        if product:
            body['product_id'] = self.product.id
        return self.client.post(f'/api/retailer/{self.shop.id}/report/', body, format='json')

    def test_report_flood_never_hides_product_or_shop(self):
        for c in self.customers:
            self.assertEqual(self.report(c).status_code, 201)
            self.assertEqual(self.report(c, product=False, reason='not_delivered').status_code, 201)
        self.product.refresh_from_db()
        self.shop.refresh_from_db()
        self.assertEqual(self.product.moderation_status, 'ok')
        self.assertEqual(self.shop.verification_status, 'approved')
        self.assertTrue(RetailerProfile.objects.public().filter(pk=self.shop.pk).exists())
        self.assertTrue(self.shop.verification_review_needed)
        # Each threshold is logged once, not once per extra report.
        self.assertEqual(VerificationEvent.objects.filter(action='product_reports_threshold').count(), 1)
        self.assertEqual(VerificationEvent.objects.filter(action='reports_threshold').count(), 1)

    def test_below_thresholds_nothing_is_flagged(self):
        for c in self.customers[:2]:
            self.report(c)
        for c in self.customers[:4]:
            self.assertEqual(self.report(c, product=False, reason='offensive').status_code, 201)
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.verification_review_needed)
        self.client.force_authenticate(self.admin)
        groups = self.client.get('/api/retailer/admin/reports/').data['results']
        self.assertEqual({g['target_type']: g['needs_review'] for g in groups}, {'product': False, 'shop': False})

    def test_old_shop_reports_do_not_count(self):
        for c in self.customers[:4]:
            self.report(c, product=False, reason='offensive')
        CustomerReport.objects.update(created_at=timezone.now() - timedelta(days=8))
        self.report(self.customers[5], product=False, reason='offensive')
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.verification_review_needed)

    def test_two_strikes_do_not_flag_three_do_and_old_ones_expire(self):
        for i in range(2):
            s = handle_reports(retailer_id=self.shop.id, product_id=None, action='strike', actor=self.admin, reason=f'v{i}')
            self.assertFalse(s['flagged_for_review'])
        RetailerStrike.objects.update(created_at=timezone.now() - timedelta(days=91))
        s = handle_reports(retailer_id=self.shop.id, product_id=None, action='strike', actor=self.admin, reason='v3')
        self.assertEqual((s['strikes_in_90_days'], s['flagged_for_review']), (1, False))
        for i in range(2):
            s = handle_reports(retailer_id=self.shop.id, product_id=None, action='strike', actor=self.admin, reason=f'w{i}')
        self.assertEqual((s['strikes_in_90_days'], s['flagged_for_review']), (3, True))
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.verification_status, 'approved')

    def test_strikes_on_a_suspended_shop_do_not_reflag(self):
        RetailerProfile.objects.filter(pk=self.shop.pk).update(verification_status='suspended', is_verified=False)
        for i in range(3):
            s = handle_reports(retailer_id=self.shop.id, product_id=None, action='strike', actor=self.admin, reason=f'v{i}')
        self.assertFalse(s['flagged_for_review'])
        self.assertFalse(VerificationEvent.objects.filter(action='strikes_threshold').exists())

    def test_dismissed_reporter_can_report_again(self):
        self.report(self.customers[0])
        handle_reports(retailer_id=self.shop.id, product_id=self.product.id, action='dismiss', actor=self.admin)
        res = self.report(self.customers[0])
        self.assertEqual(res.status_code, 201)
        self.assertEqual(CustomerReport.objects.filter(status='open').count(), 1)


@override_settings(ADMIN_EMAILS=['admin@ordereasy.in'])
class ReportEndpointNegativeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner, self.shop = make_shop()
        self.product = make_product(self.shop, 'Sugar 1kg')
        _, self.other_shop = make_shop('othershop')
        self.other_product = make_product(self.other_shop, 'Salt 1kg')
        self.customer = User.objects.create_user(username='cust', password='x', user_type='customer')
        self.admin = User.objects.create_user(username='admin', email='admin@ordereasy.in', password='x')
        self.url = f'/api/retailer/{self.shop.id}/report/'

    def test_anonymous_cannot_report(self):
        res = self.client.post(self.url, {'reason': 'misleading'}, format='json')
        self.assertIn(res.status_code, (401, 403))

    def test_bad_inputs(self):
        self.client.force_authenticate(self.customer)
        cases = [
            ({}, 'reason'),
            ({'reason': 'misleading', 'text': 'x' * 1001}, 'text'),
            ({'reason': 'misleading', 'text': ['not', 'a', 'string']}, 'text'),
            ({'reason': 'misleading', 'product_id': 'abc'}, 'product_id'),
            ({'reason': 'misleading', 'product_id': self.other_product.id}, 'product_id'),
        ]
        for body, field in cases:
            res = self.client.post(self.url, body, format='json')
            self.assertEqual(res.status_code, 400, body)
            self.assertIn(field, res.data, body)
        self.assertFalse(CustomerReport.objects.exists())

    def test_unknown_or_suspended_shop_is_404(self):
        self.client.force_authenticate(self.customer)
        self.assertEqual(self.client.post('/api/retailer/999999/report/', {'reason': 'other'}, format='json').status_code, 404)
        RetailerProfile.objects.filter(pk=self.shop.pk).update(verification_status='suspended', is_verified=False)
        self.assertEqual(self.client.post(self.url, {'reason': 'other'}, format='json').status_code, 404)

    def test_text_is_stored_trimmed_to_limit(self):
        self.client.force_authenticate(self.customer)
        res = self.client.post(self.url, {'reason': 'other', 'text': 'y' * 1000}, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(CustomerReport.objects.get().text), 1000)

    def test_admin_action_validation(self):
        self.client.force_authenticate(self.admin)
        cases = [
            ({}, 400),
            ({'retailer_id': 'x'}, 400),
            ({'retailer_id': self.shop.id, 'product_id': 'x', 'action': 'dismiss'}, 400),
            ({'retailer_id': 999999, 'action': 'dismiss'}, 404),
            ({'retailer_id': self.shop.id, 'action': 'nuke'}, 400),
            ({'retailer_id': self.shop.id, 'action': 'hide_product'}, 400),
            ({'retailer_id': self.shop.id, 'product_id': self.other_product.id, 'action': 'hide_product'}, 400),
            ({'retailer_id': self.shop.id, 'action': 'strike'}, 400),
        ]
        for body, code in cases:
            self.assertEqual(self.client.post(REPORT_ACTION_URL, body, format='json').status_code, code, body)
        self.other_product.refresh_from_db()
        self.assertEqual(self.other_product.moderation_status, 'ok')
        self.assertFalse(RetailerStrike.objects.exists())

    def test_hide_product_from_inbox(self):
        self.client.force_authenticate(self.customer)
        self.client.post(self.url, {'reason': 'misleading', 'product_id': self.product.id}, format='json')
        self.client.force_authenticate(self.admin)
        res = self.client.post(REPORT_ACTION_URL, {'retailer_id': self.shop.id, 'product_id': self.product.id,
                                                   'action': 'hide_product', 'reason': 'Wrong photo'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual((self.product.moderation_status, self.product.moderation_reason), ('hidden', 'Wrong photo'))
        self.assertEqual(self.client.get('/api/retailer/admin/reports/', {'status': 'actioned'}).data['count'], 1)
        self.assertEqual(self.client.get('/api/retailer/admin/reports/', {'status': 'bogus'}).status_code, 400)

    def test_product_moderate_validation(self):
        self.client.force_authenticate(self.admin)
        url = f'/api/retailer/admin/products/{self.product.id}/moderate/'
        self.assertEqual(self.client.post('/api/retailer/admin/products/999999/moderate/', {'action': 'approve'}, format='json').status_code, 404)
        self.assertEqual(self.client.post(url, {'action': 'delete'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(url, {'action': 'remove'}, format='json').status_code, 400)
        res = self.client.post(url, {'action': 'remove', 'reason': 'Counterfeit'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.moderation_status, 'removed')
        # An edit by the retailer never lifts an admin removal.
        self.product.name = 'Sugar 1kg pack'
        self.product.save()
        self.product.refresh_from_db()
        self.assertEqual(self.product.moderation_status, 'removed')
        self.assertEqual(self.client.get('/api/retailer/admin/products/review/', {'status': 'nope'}).status_code, 400)

    def test_retailer_and_customer_cannot_moderate(self):
        for user in (self.owner, self.customer):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.post(f'/api/retailer/admin/products/{self.product.id}/moderate/',
                                              {'action': 'approve'}, format='json').status_code, 403)
            self.assertEqual(self.client.post(REPORT_ACTION_URL, {'retailer_id': self.shop.id, 'action': 'dismiss'},
                                              format='json').status_code, 403)
