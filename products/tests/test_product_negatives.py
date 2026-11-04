"""Catalog negatives: bad price/stock, duplicate barcode/name, other retailers' products, roles, delete in open order."""
from decimal import Decimal

import pytest
from django.urls import reverse

from authentication.models import User
from products.models import Product
from retailers.models import RetailerProfile


@pytest.fixture
def other_shop(db):
    owner = User.objects.create_user(username='cat_other', email='cat_other@t.com', password='TestPass123!',
                                     user_type='retailer', is_active=True)
    return RetailerProfile.objects.create(user=owner, shop_name='Other Shop', address_line1='1 St', city='C',
                                          state='S', pincode='123456', is_active=True, is_verified=True,
                                          verification_status='approved')


def create(client, user, **fields):
    client.force_authenticate(user=user)
    data = {'name': 'Fresh Item', 'price': '10.00', 'quantity': 5, 'unit': 'piece', **fields}
    return client.post(reverse('create_product'), data, format='json')


@pytest.mark.django_db
class TestCreateRefusals:
    @pytest.mark.parametrize('fields', [{'price': '-1'}, {'price': 'abc'}, {'quantity': 'x'},
                                        {'name': ''}])
    def test_bad_fields_create_nothing(self, api_client, retailer, fields):
        before = Product.objects.count()
        r = create(api_client, retailer.user, **fields)
        assert r.status_code == 400, r.content
        assert Product.objects.count() == before

    @pytest.mark.xfail(strict=True, reason='OE-395: create_product accepts quantity=-5 (201), product starts with negative stock')
    def test_negative_opening_stock_is_refused(self, api_client, retailer):
        before = Product.objects.count()
        r = create(api_client, retailer.user, quantity=-5)
        assert r.status_code == 400
        assert Product.objects.count() == before

    def test_duplicate_barcode_in_same_shop(self, api_client, retailer, product):
        product.barcode = '8900000000017'
        product.save()
        r = create(api_client, retailer.user, barcode='8900000000017')
        assert r.status_code == 400
        assert 'A product with this barcode already exists.' in str(r.json())

    def test_duplicate_name_in_same_shop(self, api_client, retailer, product):
        r = create(api_client, retailer.user, name=product.name)
        assert r.status_code == 400
        assert 'A product with this name already exists.' in str(r.json())

    def test_same_barcode_in_another_shop_is_allowed(self, api_client, other_shop, product):
        product.barcode = '8900000000024'
        product.save()
        assert create(api_client, other_shop.user, barcode='8900000000024').status_code == 201

    def test_customer_cannot_create(self, api_client, customer):
        r = create(api_client, customer)
        assert r.status_code == 403
        assert r.json() == {'error': 'Only retailers can create products'}


@pytest.mark.django_db
class TestOtherRetailersProduct:
    def test_cannot_update(self, api_client, other_shop, product):
        api_client.force_authenticate(user=other_shop.user)
        r = api_client.patch(reverse('update_product', args=[product.id]), {'price': '1.00'}, format='json')
        assert r.status_code == 404
        product.refresh_from_db()
        assert product.price == Decimal('90.00')

    def test_cannot_delete(self, api_client, other_shop, product):
        api_client.force_authenticate(user=other_shop.user)
        assert api_client.delete(reverse('delete_product', args=[product.id])).status_code == 404
        product.refresh_from_db()
        assert product.is_active

    def test_cannot_read_detail(self, api_client, other_shop, product):
        api_client.force_authenticate(user=other_shop.user)
        assert api_client.get(reverse('get_product_detail', args=[product.id])).status_code == 404

    def test_not_in_their_list(self, api_client, other_shop, product):
        api_client.force_authenticate(user=other_shop.user)
        r = api_client.get(reverse('get_retailer_products'))
        assert product.id not in [p['id'] for p in (r.json().get('results', r.json()))]


@pytest.mark.django_db
class TestUpdateRefusals:
    @pytest.mark.parametrize('fields', [{'price': '-5'}, {'price': 'abc'}])
    def test_bad_update_leaves_product(self, api_client, retailer, product, fields):
        api_client.force_authenticate(user=retailer.user)
        r = api_client.patch(reverse('update_product', args=[product.id]), fields, format='json')
        assert r.status_code == 400, r.content
        product.refresh_from_db()
        assert product.price == Decimal('90.00')

    def test_customer_cannot_delete(self, api_client, customer, product):
        api_client.force_authenticate(user=customer)
        assert api_client.delete(reverse('delete_product', args=[product.id])).status_code == 403
        product.refresh_from_db()
        assert product.is_active


@pytest.mark.django_db
def test_deleting_a_product_in_an_open_order_keeps_the_order(api_client, retailer, product, customer, address):
    from orders.models import Order, OrderItem
    order = Order.objects.create(customer=customer, retailer=retailer, delivery_mode='delivery', payment_mode='cash',
                                 delivery_address=address, subtotal=Decimal('180'), total_amount=Decimal('180'),
                                 status='pending')
    OrderItem.objects.create(order=order, product=product, product_name=product.name, product_price=product.price,
                             quantity=2, unit_price=product.price, total_price=Decimal('180'))
    api_client.force_authenticate(user=retailer.user)
    assert api_client.delete(reverse('delete_product', args=[product.id])).status_code == 200
    product.refresh_from_db()
    assert product.is_active is False
    order.refresh_from_db()
    assert order.status == 'pending'
    assert order.items.get().product_id == product.id
