"""Negative paths for orders and cart: each test checks the exact error body and that nothing changed."""
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from authentication.models import User
from cart.models import Cart, CartItem
from orders.models import Order
from products.models import Product
from retailers.models import RetailerProfile

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_notifications():
    with patch('common.notifications.send_push_notification'), patch('common.notifications.send_silent_update'):
        yield


@pytest.fixture
def verified_customer(customer):
    customer.is_phone_verified = True
    customer.save(update_fields=['is_phone_verified'])
    return customer


@pytest.fixture
def other_retailer_user():
    return User.objects.create_user(
        username='other_retailer', email='other_retailer@test.com', password='TestPass123!',
        user_type='retailer', is_active=True,
    )


@pytest.fixture
def other_retailer(other_retailer_user):
    return RetailerProfile.objects.create(
        is_verified=True, verification_status='approved', user=other_retailer_user, shop_name='Other Shop',
        address_line1='1 Side St', city='TestCity', state='TestState', pincode='123456', is_active=True,
        offers_delivery=True, offers_pickup=True, minimum_order_amount=Decimal('0'),
    )


@pytest.fixture
def other_product(other_retailer, category, brand):
    return Product.objects.create(
        retailer=other_retailer, name='Other Product', category=category, brand=brand, price=Decimal('10.00'),
        quantity=5, track_inventory=True, is_active=True, is_available=True, minimum_order_quantity=1, unit='piece',
    )


def place(client, retailer, address, **extra):
    data = {'retailer_id': retailer.id, 'delivery_mode': 'delivery', 'payment_mode': 'cash', 'address_id': address.id}
    data.update(extra)
    return client.post(reverse('place_order'), data, format='json')


def stock(product):
    product.refresh_from_db()
    return product.quantity


# --- place order ---------------------------------------------------------------------------------

def test_place_order_unauthenticated_is_refused(api_client, cart_with_items, retailer, address, product):
    res = place(api_client, retailer, address)
    assert res.status_code == 401
    assert res.json() == {'detail': 'Authentication credentials were not provided.'}
    assert Order.objects.count() == 0
    assert stock(product) == 50


def test_place_order_as_retailer_is_forbidden(api_client, retailer_user, retailer, address):
    api_client.force_authenticate(retailer_user)
    res = place(api_client, retailer, address)
    assert res.status_code == 403
    assert res.json() == {'error': 'Only customers can place orders'}
    assert Order.objects.count() == 0


def test_place_order_needs_verified_phone(api_client, customer, cart_with_items, retailer, address, product):
    api_client.force_authenticate(customer)
    res = place(api_client, retailer, address)
    assert res.status_code == 403
    assert res.json() == {'error': 'Please verify your phone number to place orders.'}
    assert Order.objects.count() == 0
    assert stock(product) == 50


def test_place_order_with_empty_cart(api_client, verified_customer, retailer, address):
    api_client.force_authenticate(verified_customer)
    res = place(api_client, retailer, address)
    assert res.status_code == 400
    assert res.json() == {'non_field_errors': ['Cart is empty']}
    assert Order.objects.count() == 0


def test_place_order_with_cart_emptied(api_client, verified_customer, retailer, address):
    Cart.objects.create(customer=verified_customer, retailer=retailer)
    api_client.force_authenticate(verified_customer)
    res = place(api_client, retailer, address)
    assert res.status_code == 400
    assert res.json() == {'non_field_errors': ['Cart is empty']}


def test_place_order_unknown_retailer(api_client, verified_customer, address):
    api_client.force_authenticate(verified_customer)
    res = api_client.post(reverse('place_order'), {
        'retailer_id': 999999, 'delivery_mode': 'delivery', 'payment_mode': 'cash', 'address_id': address.id,
    }, format='json')
    assert res.status_code == 400
    assert res.json()['retailer_id'] == ['Retailer not found']
    assert Order.objects.count() == 0


def test_place_order_delivery_without_address(api_client, verified_customer, cart_with_items, retailer, product):
    api_client.force_authenticate(verified_customer)
    res = api_client.post(reverse('place_order'), {
        'retailer_id': retailer.id, 'delivery_mode': 'delivery', 'payment_mode': 'cash',
    }, format='json')
    assert res.status_code == 400
    assert res.json() == {'non_field_errors': ['Address is required for delivery orders']}
    assert Order.objects.count() == 0
    assert stock(product) == 50


def test_place_order_with_someone_elses_address(api_client, verified_customer, cart_with_items, retailer, other_retailer_user):
    from customers.models import CustomerAddress
    stranger = User.objects.create_user(username='stranger', password='x', user_type='customer')
    foreign = CustomerAddress.objects.create(
        customer=stranger, title='Home', address_type='home', address_line1='9 Far St',
        city='TestCity', state='TestState', pincode='123456',
    )
    api_client.force_authenticate(verified_customer)
    res = place(api_client, retailer, foreign)
    assert res.status_code == 400
    assert res.json() == {'address_id': ['Address not found']}
    assert Order.objects.count() == 0


def test_place_order_bad_payment_mode_for_delivery(api_client, verified_customer, cart_with_items, retailer, address):
    api_client.force_authenticate(verified_customer)
    res = place(api_client, retailer, address, payment_mode='cash_pickup')
    assert res.status_code == 400
    assert res.json() == {'non_field_errors': ['Invalid payment mode for delivery']}
    assert Order.objects.count() == 0


def test_place_order_bad_payment_mode_for_pickup(api_client, verified_customer, cart_with_items, retailer, address):
    api_client.force_authenticate(verified_customer)
    res = place(api_client, retailer, address, delivery_mode='pickup', payment_mode='cash')
    assert res.status_code == 400
    assert res.json() == {'non_field_errors': ['Invalid payment mode for pickup']}
    assert Order.objects.count() == 0


def test_place_order_unknown_payment_mode(api_client, verified_customer, cart_with_items, retailer, address):
    api_client.force_authenticate(verified_customer)
    res = place(api_client, retailer, address, payment_mode='bitcoin')
    assert res.status_code == 400
    assert res.json() == {'payment_mode': ['"bitcoin" is not a valid choice.']}
    assert Order.objects.count() == 0


def test_place_order_pickup_when_retailer_has_no_pickup(api_client, verified_customer, cart_with_items, retailer, address):
    retailer.offers_pickup = False
    retailer.save(update_fields=['offers_pickup'])
    api_client.force_authenticate(verified_customer)
    res = place(api_client, retailer, address, delivery_mode='pickup', payment_mode='cash_pickup')
    assert res.status_code == 400
    assert res.json() == {'non_field_errors': ['This retailer does not offer store pickup.']}
    assert Order.objects.count() == 0


def test_place_order_delivery_when_retailer_has_no_delivery(api_client, verified_customer, cart_with_items, retailer, address):
    retailer.offers_delivery = False
    retailer.save(update_fields=['offers_delivery'])
    api_client.force_authenticate(verified_customer)
    res = place(api_client, retailer, address)
    assert res.status_code == 400
    assert res.json() == {'non_field_errors': ['This retailer does not offer delivery.']}
    assert Order.objects.count() == 0


def test_place_order_over_stock_leaves_stock_alone(api_client, verified_customer, retailer, address, product):
    cart = Cart.objects.create(customer=verified_customer, retailer=retailer)
    CartItem.objects.create(cart=cart, product=product, quantity=5, unit_price=product.price)
    Product.objects.filter(pk=product.pk).update(quantity=3)
    api_client.force_authenticate(verified_customer)
    res = place(api_client, retailer, address)
    assert res.status_code == 400
    [msg] = res.json()['non_field_errors']
    assert "'Order Product'" in msg and 'available' in msg
    assert Order.objects.count() == 0
    assert stock(product) == 3
    assert cart.items.count() == 1


def test_place_order_above_maximum_quantity(api_client, verified_customer, retailer, address, product):
    cart = Cart.objects.create(customer=verified_customer, retailer=retailer)
    CartItem.objects.create(cart=cart, product=product, quantity=11, unit_price=product.price)
    api_client.force_authenticate(verified_customer)
    res = place(api_client, retailer, address)
    assert res.status_code == 400
    assert res.json() == {'non_field_errors': ["Product 'Order Product' - maximum order quantity is 10.000"]}  # OE-397: should read 10
    assert Order.objects.count() == 0
    assert stock(product) == 50


def test_place_order_with_hidden_product(api_client, verified_customer, cart_with_items, retailer, address, product):
    Product.objects.filter(pk=product.pk).update(is_active=False)
    api_client.force_authenticate(verified_customer)
    res = place(api_client, retailer, address)
    assert res.status_code == 400
    assert res.json() == {'non_field_errors': ["Product 'Order Product' is no longer available. Remove it from your cart."]}
    assert Order.objects.count() == 0


# --- cart -----------------------------------------------------------------------------------------

@pytest.mark.parametrize('qty, error', [
    (0, 'Quantity must be greater than 0'),
    (-2, 'Quantity must be greater than 0'),
    ('abc', 'A valid number is required.'),
])
def test_add_to_cart_bad_quantity(api_client, verified_customer, product, qty, error):
    api_client.force_authenticate(verified_customer)
    res = api_client.post(reverse('add_to_cart'), {'product_id': product.id, 'quantity': qty}, format='json')
    assert res.status_code == 400
    assert res.json() == {'quantity': [error]}
    assert CartItem.objects.count() == 0


def test_add_to_cart_unknown_product(api_client, verified_customer):
    api_client.force_authenticate(verified_customer)
    res = api_client.post(reverse('add_to_cart'), {'product_id': 999999, 'quantity': 1}, format='json')
    assert res.status_code == 400
    assert res.json() == {'product_id': ['Product not found or not available']}
    assert CartItem.objects.count() == 0


def test_add_to_cart_inactive_product(api_client, verified_customer, product):
    Product.objects.filter(pk=product.pk).update(is_available=False)
    api_client.force_authenticate(verified_customer)
    res = api_client.post(reverse('add_to_cart'), {'product_id': product.id, 'quantity': 1}, format='json')
    assert res.status_code == 400
    assert res.json() == {'product_id': ['Product not found or not available']}
    assert CartItem.objects.count() == 0


def test_add_to_cart_as_retailer_is_forbidden(api_client, retailer_user, product):
    api_client.force_authenticate(retailer_user)
    res = api_client.post(reverse('add_to_cart'), {'product_id': product.id, 'quantity': 1}, format='json')
    assert res.status_code == 403
    assert res.json() == {'error': 'Only customers can add items to cart'}
    assert CartItem.objects.count() == 0


def test_add_to_cart_unauthenticated(api_client, product):
    res = api_client.post(reverse('add_to_cart'), {'product_id': product.id, 'quantity': 1}, format='json')
    assert res.status_code == 401
    assert CartItem.objects.count() == 0


def test_cart_lines_stay_per_retailer(api_client, verified_customer, cart_with_items, retailer, address, other_product):
    """A product from another shop goes to that shop's cart, never into this retailer's order."""
    api_client.force_authenticate(verified_customer)
    res = api_client.post(reverse('add_to_cart'), {'product_id': other_product.id, 'quantity': 1}, format='json')
    assert res.status_code == 201
    order = place(api_client, retailer, address)
    assert order.status_code == 201, order.content
    placed = Order.objects.get()
    assert placed.retailer_id == retailer.id
    assert not placed.items.filter(product=other_product).exists()
    assert stock(other_product) == 5


def test_clear_cart_needs_retailer_id(api_client, verified_customer):
    api_client.force_authenticate(verified_customer)
    res = api_client.post(reverse('clear_cart'), {}, format='json')
    assert res.status_code == 400
    assert res.json() == {'error': 'Retailer ID is required'}


def test_apply_coupon_on_empty_cart(api_client, verified_customer, retailer):
    api_client.force_authenticate(verified_customer)
    res = api_client.post(reverse('cart_apply_coupon'), {'retailer_id': retailer.id, 'coupon_code': 'NOPE'}, format='json')
    assert res.status_code == 400
    assert res.json() == {'error': 'Your cart is empty'}


def test_apply_coupon_needs_code(api_client, verified_customer, retailer):
    api_client.force_authenticate(verified_customer)
    res = api_client.post(reverse('cart_apply_coupon'), {'retailer_id': retailer.id}, format='json')
    assert res.status_code == 400
    assert res.json() == {'error': 'coupon_code is required'}


# --- cross-tenant and roles -----------------------------------------------------------------------

def test_other_retailer_cannot_read_order(api_client, other_retailer, other_retailer_user, order):
    api_client.force_authenticate(other_retailer_user)
    res = api_client.get(reverse('get_order_detail', args=[order.id]))
    assert res.status_code == 404
    assert res.json() == {'error': 'Order not found'}


def test_other_retailer_cannot_change_status(api_client, other_retailer, other_retailer_user, order):
    api_client.force_authenticate(other_retailer_user)
    res = api_client.patch(reverse('update_order_status', args=[order.id]), {'status': 'confirmed'}, format='json')
    assert res.status_code == 404
    assert res.json() == {'error': 'Order not found'}
    order.refresh_from_db()
    assert order.status == 'pending'


def test_other_retailer_cannot_cancel(api_client, other_retailer, other_retailer_user, order):
    api_client.force_authenticate(other_retailer_user)
    res = api_client.post(reverse('cancel_order', args=[order.id]), {}, format='json')
    assert res.status_code == 404
    assert res.json() == {'error': 'Order not found'}
    order.refresh_from_db()
    assert order.status == 'pending'


def test_other_retailer_order_lists_exclude_order(api_client, other_retailer, other_retailer_user, order):
    api_client.force_authenticate(other_retailer_user)
    for name in ('get_current_orders', 'get_order_history'):
        res = api_client.get(reverse(name))
        assert res.status_code == 200
        body = res.json()
        rows = body.get('results', body) if isinstance(body, dict) else body
        assert order.id not in [r['id'] for r in rows], name


def test_other_customer_cannot_read_or_cancel(api_client, order):
    stranger = User.objects.create_user(username='stranger2', password='x', user_type='customer')
    api_client.force_authenticate(stranger)
    assert api_client.get(reverse('get_order_detail', args=[order.id])).json() == {'error': 'Order not found'}
    res = api_client.post(reverse('cancel_order', args=[order.id]), {}, format='json')
    assert res.status_code == 404
    order.refresh_from_db()
    assert order.status == 'pending'


def test_customer_cannot_change_status(api_client, customer, order):
    api_client.force_authenticate(customer)
    res = api_client.patch(reverse('update_order_status', args=[order.id]), {'status': 'confirmed'}, format='json')
    assert res.status_code == 403
    assert res.json() == {'error': 'Only retailers can update order status'}
    order.refresh_from_db()
    assert order.status == 'pending'


# --- status rules ---------------------------------------------------------------------------------

@pytest.mark.parametrize('start, target', [
    ('packed', 'confirmed'),
    ('confirmed', 'delivered'),
    ('confirmed', 'out_for_delivery'),
    ('cancelled', 'confirmed'),
    ('delivered', 'cancelled'),
])
def test_refused_transitions(api_client, retailer_user, retailer, order, start, target):
    Order.objects.filter(pk=order.pk).update(status=start)
    api_client.force_authenticate(retailer_user)
    res = api_client.patch(reverse('update_order_status', args=[order.id]), {'status': target}, format='json')
    assert res.status_code == 400
    assert res.json() == {'status': [f"Cannot change status from '{start}' to '{target}'"]}
    order.refresh_from_db()
    assert order.status == start


def test_unknown_status_value(api_client, retailer_user, retailer, order):
    api_client.force_authenticate(retailer_user)
    res = api_client.patch(reverse('update_order_status', args=[order.id]), {'status': 'teleported'}, format='json')
    assert res.status_code == 400
    assert res.json() == {'status': ['"teleported" is not a valid choice.']}
    order.refresh_from_db()
    assert order.status == 'pending'


@pytest.mark.parametrize('start', ['packed', 'delivered', 'cancelled'])
def test_retailer_cannot_cancel_late(api_client, retailer_user, retailer, order, product, start):
    Order.objects.filter(pk=order.pk).update(status=start)
    api_client.force_authenticate(retailer_user)
    res = api_client.post(reverse('cancel_order', args=[order.id]), {}, format='json')
    assert res.status_code == 400
    assert res.json() == {'error': 'Order cannot be cancelled'}
    order.refresh_from_db()
    assert order.status == start
    assert stock(product) == 50


@pytest.mark.xfail(strict=True, reason=(
    'OE-398 (same cause as OE-392): OrderFeedbackSerializer.create raises ValidationError after is_valid(), '
    'so create_order_feedback answers 500 instead of 400.'
))
def test_feedback_before_delivery(api_client, customer, order):
    api_client.force_authenticate(customer)
    res = api_client.post(reverse('create_order_feedback', args=[order.id]), {
        'overall_rating': 5, 'product_quality_rating': 5, 'delivery_rating': 5, 'service_rating': 5,
    }, format='json')
    assert res.status_code == 400
    assert res.json() == ['Can only provide feedback for delivered orders']
    assert not hasattr(Order.objects.get(pk=order.pk), 'feedback')


@pytest.mark.xfail(strict=True, reason=(
    'OE-392 (same cause as OE-398): OrderReturnSerializer.create raises ValidationError after is_valid(), '
    'so create_return_request catches it as a generic Exception and answers 500 instead of 400.'
))
def test_return_before_delivery(api_client, customer, order):
    api_client.force_authenticate(customer)
    res = api_client.post(reverse('create_return_request', args=[order.id]), {'reason': 'damaged', 'description': 'x'}, format='json')
    assert res.status_code == 400
    assert res.json() == ['Can only return delivered orders']
    assert not hasattr(Order.objects.get(pk=order.pk), 'return_request')


def test_chat_message_cannot_be_empty(api_client, customer, order):
    api_client.force_authenticate(customer)
    res = api_client.post(reverse('send_order_message', args=[order.id]), {'message': ''}, format='json')
    assert res.status_code == 400
    assert res.json() == {'error': 'Message cannot be empty'}
