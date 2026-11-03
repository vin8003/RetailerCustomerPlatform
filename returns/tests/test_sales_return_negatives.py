"""Sales return (POS counter) negatives: over-returns, price above sale, other shops' orders, bad lines.

Each refusal re-reads stock and the return table to prove nothing was written.
"""
from decimal import Decimal

import pytest
from django.urls import reverse

from authentication.models import User
from orders.models import Order, OrderItem
from retailers.models import RetailerProfile
from returns.models import SalesReturn

URL = 'sales-return-list'


@pytest.fixture
def sold(retailer, customer, product):
    order = Order.objects.create(retailer=retailer, customer=customer, subtotal=Decimal('900'),
                                 total_amount=Decimal('900'), status='delivered', payment_mode='cash')
    item = OrderItem.objects.create(order=order, product=product, product_name=product.name,
                                    product_price=product.price, product_unit=product.unit, quantity=10,
                                    unit_price=Decimal('90.00'), total_price=Decimal('900.00'))
    return order, item


def ret(client, user, order, item, product, quantity=1, price='90.00', **extra):
    client.force_authenticate(user=user)
    body = {'order_id': order.id, 'refund_payment_mode': 'cash',
            'items': [{'product_id': product.id, 'order_item_id': item.id, 'quantity': quantity,
                       'refund_unit_price': price}], **extra}
    return client.post(reverse(URL), body, format='json')


def assert_untouched(product, stock=50):
    product.refresh_from_db()
    assert product.quantity == stock
    assert SalesReturn.objects.count() == 0


@pytest.mark.django_db
class TestSalesReturnRefusals:
    def test_no_items(self, api_client, retailer_user, retailer, sold, product):
        api_client.force_authenticate(user=retailer_user)
        r = api_client.post(reverse(URL), {'order_id': sold[0].id, 'items': []}, format='json')
        assert r.status_code == 400
        assert r.json() == {'error': 'No items provided for return'}
        assert_untouched(product)

    @pytest.mark.parametrize('qty', [0, -1, 'x'])
    def test_bad_quantity(self, api_client, retailer_user, retailer, sold, product, qty):
        r = ret(api_client, retailer_user, *sold, product, quantity=qty)
        assert r.status_code == 400
        assert 'quantity' in r.json()['error']
        assert_untouched(product)

    def test_more_than_sold(self, api_client, retailer_user, retailer, sold, product):
        r = ret(api_client, retailer_user, *sold, product, quantity=11)
        assert r.status_code == 400, r.content
        assert_untouched(product)

    def test_second_return_cannot_exceed_what_is_left(self, api_client, retailer_user, retailer, sold, product):
        assert ret(api_client, retailer_user, *sold, product, quantity=6).status_code == 201
        product.refresh_from_db()
        stock_after_first = product.quantity
        r = ret(api_client, retailer_user, *sold, product, quantity=6)
        assert r.status_code == 400, r.content
        product.refresh_from_db()
        assert product.quantity == stock_after_first
        assert SalesReturn.objects.count() == 1

    # TODO(bug): the refund price is not capped at what the line sold for. Repro: delivered order,
    # line 10 x 90.00; POST /api/returns/sales/ {"order_id", "items": [{"product_id", "order_item_id",
    # "quantity": 1, "refund_unit_price": 5000}]} -> 201 with refund_amount "5000.00". Expect 400.
    @pytest.mark.xfail(strict=True, reason='sales return refund can exceed the sale price')
    def test_refund_above_sale_price(self, api_client, retailer_user, retailer, sold, product):
        r = ret(api_client, retailer_user, *sold, product, price='5000')
        assert r.status_code == 400, r.content
        assert_untouched(product)

    def test_negative_refund_price(self, api_client, retailer_user, retailer, sold, product):
        r = ret(api_client, retailer_user, *sold, product, price='-1')
        assert r.status_code == 400
        assert 'refund_unit_price' in r.json()['error']
        assert_untouched(product)

    def test_notes_must_be_text(self, api_client, retailer_user, retailer, sold, product):
        r = ret(api_client, retailer_user, *sold, product, notes={'x': 1})
        assert r.status_code == 400
        assert r.json() == {'error': 'notes must be text'}
        assert_untouched(product)

    def test_line_product_mismatch(self, api_client, retailer_user, retailer, sold, product, product2):
        order, item = sold
        r = ret(api_client, retailer_user, order, item, product2, price=str(product2.price))
        assert r.status_code == 400
        assert r.json() == {'error': f'{product2.name} is not the product on that order line'}
        assert_untouched(product)

    def test_other_shop_cannot_return_my_order(self, api_client, retailer, sold, product):
        owner = User.objects.create_user(username='ret_other', email='ro@t.com', password='TestPass123!',
                                         user_type='retailer', is_active=True)
        RetailerProfile.objects.create(user=owner, shop_name='Ret Other', address_line1='1', city='C', state='S',
                                       pincode='123456', is_active=True, is_verified=True,
                                       verification_status='approved')
        r = ret(api_client, owner, *sold, product)
        assert r.status_code in (403, 404)
        assert_untouched(product)

    def test_customer_cannot_create_counter_return(self, api_client, customer, sold, product):
        r = ret(api_client, customer, *sold, product)
        assert r.status_code in (403, 404)
        assert_untouched(product)
