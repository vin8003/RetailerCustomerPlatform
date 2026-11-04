"""POS bill negatives: bad quantities, over stock, discount above the bill, other shops' goods.

Every refusal re-reads stock and the order table to prove nothing was written.
"""
from decimal import Decimal

import pytest
from django.urls import reverse

from authentication.models import User
from orders.models import Order
from products.models import Product
from retailers.models import RetailerProfile

URL = 'create_pos_order'


def bill(client, user, items, **extra):
    client.force_authenticate(user=user)
    return client.post(reverse(URL), {'payment_mode': 'cash', 'items': items, **extra}, format='json')


def line(product, quantity=1, unit_price='90.00'):
    return {'product_id': product.id, 'quantity': quantity, 'unit_price': unit_price}


def assert_nothing_written(product, stock=50):
    product.refresh_from_db()
    assert product.quantity == stock
    assert Order.objects.count() == 0


@pytest.fixture
def other_shop_product(category, brand):
    owner = User.objects.create_user(username='pos_other', email='pos_other@t.com', password='TestPass123!',
                                     user_type='retailer', is_active=True)
    shop = RetailerProfile.objects.create(user=owner, shop_name='Other POS Shop', address_line1='1 St', city='C',
                                          state='S', pincode='123456', is_active=True, is_verified=True,
                                          verification_status='approved')
    return Product.objects.create(retailer=shop, name='Other Sugar', category=category, brand=brand,
                                  price=Decimal('40.00'), quantity=10, track_inventory=True,
                                  is_active=True, is_available=True)


@pytest.mark.django_db
class TestPosBillRefusals:
    def test_empty_items(self, api_client, retailer_user, retailer, product):
        r = bill(api_client, retailer_user, [])
        assert r.status_code == 400
        assert r.json() == {'error': 'Cart is empty.'}
        assert_nothing_written(product)

    @pytest.mark.parametrize('qty, message', [
        (0, 'Must be more than zero.'),
        (-2, 'Must be more than zero.'),
        ('abc', None),
        (10 ** 10, 'Is too large.'),
    ])
    def test_bad_quantity(self, api_client, retailer_user, retailer, product, qty, message):
        r = bill(api_client, retailer_user, [line(product, quantity=qty)])
        assert r.status_code == 400
        assert 'quantity' in r.json()['error']
        if message:
            assert message in r.json()['error']
        assert_nothing_written(product)

    def test_negative_unit_price(self, api_client, retailer_user, retailer, product):
        r = bill(api_client, retailer_user, [line(product, unit_price='-90')])
        assert r.status_code == 400
        assert 'unit_price' in r.json()['error'] and 'Cannot be negative.' in r.json()['error']
        assert_nothing_written(product)

    def test_price_tampering(self, api_client, retailer_user, retailer, product):
        r = bill(api_client, retailer_user, [line(product, unit_price='1.00')])
        assert r.status_code == 400
        assert 'Price mismatch' in r.json()['error']
        assert_nothing_written(product)

    def test_negative_discount(self, api_client, retailer_user, retailer, product):
        r = bill(api_client, retailer_user, [line(product)], discount_amount='-50')
        assert r.status_code == 400
        assert 'discount_amount' in r.json()['error']
        assert_nothing_written(product)

    def test_over_stock_without_oversell_flag(self, api_client, retailer_user, retailer, product):
        r = bill(api_client, retailer_user, [line(product, quantity=51)])
        assert r.status_code == 400, r.content
        assert_nothing_written(product)

    def test_other_shops_product(self, api_client, retailer_user, retailer, product, other_shop_product):
        r = bill(api_client, retailer_user, [line(other_shop_product, unit_price='40.00')])
        assert r.status_code == 400
        assert r.json()['error'] == f'Product id={other_shop_product.id} is not in this shop.'
        other_shop_product.refresh_from_db()
        assert other_shop_product.quantity == 10
        assert_nothing_written(product)

    def test_split_payment_not_matching_total(self, api_client, retailer_user, retailer, product):
        r = bill(api_client, retailer_user, [line(product)], payment_details={'cash': '10', 'upi': '5'})
        assert r.status_code == 400
        assert 'does not match order total' in r.json()['error']
        assert_nothing_written(product)

    def test_customer_cannot_bill(self, api_client, customer, product):
        r = bill(api_client, customer, [line(product)])
        assert r.status_code == 403
        assert_nothing_written(product)


@pytest.mark.django_db
class TestPosDiscountCap:
    def test_discount_above_bill_is_capped_at_subtotal(self, api_client, retailer_user, retailer, product):
        r = bill(api_client, retailer_user, [line(product)], discount_amount='500')
        assert r.status_code == 201, r.content
        order = Order.objects.get()
        assert order.discount_amount == Decimal('90.00')
        assert order.total_amount >= 0
