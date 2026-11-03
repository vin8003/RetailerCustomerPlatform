"""Coupon negatives at the cart: expired, not started, inactive, min order, other shop's code, limits, stacking."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from authentication.models import User
from offers.models import Offer
from retailers.models import RetailerProfile


def coupon(retailer, code, **fields):
    return Offer.objects.create(retailer=retailer, name=code, offer_type='percentage', value=Decimal('10'),
                                coupon_code=code, is_active=True, **fields)


def apply(client, user, retailer, code):
    client.force_authenticate(user=user)
    return client.post(reverse('cart_apply_coupon'), {'retailer_id': retailer.id, 'coupon_code': code}, format='json')


def applied_code(cart):
    cart.refresh_from_db()
    return cart.applied_coupon_code


@pytest.mark.django_db
class TestCouponRefusals:
    @pytest.mark.parametrize('fields, error', [
        ({'end_date': timezone.now() - timedelta(days=1)}, 'This coupon code has expired'),
        ({'start_date': timezone.now() + timedelta(days=1)}, 'This coupon offer has not started yet'),
        ({'applicable_on': 'pos'}, 'This coupon is valid only in-store (POS)'),
        ({'usage_limit_total': 1, 'current_redemptions': 1}, 'This coupon usage limit has been reached'),
    ])
    def test_refused_with_reason(self, api_client, customer, retailer, cart, cart_item, fields, error):
        coupon(retailer, 'BADONE', **fields)
        r = apply(api_client, customer, retailer, 'BADONE')
        assert r.status_code == 400
        assert r.json() == {'error': error}
        assert applied_code(cart) is None

    def test_inactive_coupon_is_unknown(self, api_client, customer, retailer, cart, cart_item):
        Offer.objects.filter(pk=coupon(retailer, 'OFFNOW').pk).update(is_active=False)
        r = apply(api_client, customer, retailer, 'OFFNOW')
        assert r.json() == {'error': 'Invalid coupon code'}
        assert applied_code(cart) is None

    def test_min_order_not_met(self, api_client, customer, retailer, cart, cart_item):
        coupon(retailer, 'BIGBASKET', min_order_value=Decimal('100000'))
        r = apply(api_client, customer, retailer, 'BIGBASKET')
        assert r.status_code == 400
        assert r.json()['error'].startswith('Add ₹') and 'Min order ₹100000' in r.json()['error']
        assert applied_code(cart) is None

    def test_another_shops_code_does_not_apply(self, api_client, customer, retailer, cart, cart_item):
        owner = User.objects.create_user(username='cp_other', email='cp@t.com', password='TestPass123!',
                                         user_type='retailer', is_active=True)
        other = RetailerProfile.objects.create(user=owner, shop_name='Other', address_line1='1', city='C', state='S',
                                               pincode='123456', is_active=True, is_verified=True,
                                               verification_status='approved')
        coupon(other, 'THEIRS')
        r = apply(api_client, customer, retailer, 'THEIRS')
        assert r.json() == {'error': 'Invalid coupon code'}
        assert applied_code(cart) is None

    def test_selected_customers_only(self, api_client, customer, retailer, cart, cart_item):
        coupon(retailer, 'VIPONLY', target_audience='selected')
        assert apply(api_client, customer, retailer, 'VIPONLY').json() == {'error': 'This coupon is not valid for your account'}

    def test_retailer_cannot_apply(self, api_client, retailer, cart, cart_item):
        coupon(retailer, 'SHOPSELF')
        r = apply(api_client, retailer.user, retailer, 'SHOPSELF')
        assert r.status_code == 403

    def test_missing_retailer_id(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        r = api_client.post(reverse('cart_apply_coupon'), {'coupon_code': 'X'}, format='json')
        assert r.json() == {'error': 'retailer_id is required'}

    def test_second_coupon_replaces_first_no_stacking(self, api_client, customer, retailer, cart, cart_item):
        coupon(retailer, 'FIRST10')
        coupon(retailer, 'SECOND10')
        assert apply(api_client, customer, retailer, 'FIRST10').status_code == 200
        r = apply(api_client, customer, retailer, 'SECOND10')
        assert r.status_code == 200
        assert applied_code(cart) == 'SECOND10'
