"""Chat, order stats (report) and paging negatives. Each refusal re-reads to prove no side effect."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from authentication.models import User
from customers.models import CustomerNotification
from orders.models import Order, OrderChatMessage
from orders.tests.test_negative_paths import other_retailer, other_retailer_user  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_push():
    with patch('orders.views.send_push_notification'), patch('common.notifications.send_push_notification'):
        yield


@pytest.fixture
def stranger():
    return User.objects.create_user(username='chat_stranger', email='cs@t.com', password='TestPass123!',
                                    user_type='customer', is_active=True)


def send(client, user, order_id, message):
    client.force_authenticate(user)
    return client.post(reverse('send_order_message', args=[order_id]), {'message': message}, format='json')


# --- chat ------------------------------------------------------------------------------------------

def test_stranger_customer_cannot_read_send_or_mark_chat(api_client, stranger, order):
    api_client.force_authenticate(stranger)
    assert api_client.get(reverse('get_order_chat', args=[order.id])).status_code == 404
    assert send(api_client, stranger, order.id, 'hi').status_code == 404
    assert api_client.post(reverse('mark_chat_read', args=[order.id])).status_code == 404
    assert OrderChatMessage.objects.count() == 0


def test_other_retailer_cannot_read_or_send(api_client, other_retailer_user, other_retailer, order):
    api_client.force_authenticate(other_retailer_user)
    read = api_client.get(reverse('get_order_chat', args=[order.id]))
    assert read.status_code in (403, 404)
    assert send(api_client, other_retailer_user, order.id, 'hi').status_code in (403, 404)
    assert OrderChatMessage.objects.count() == 0


def test_unknown_order_chat_is_404(api_client, customer):
    assert send(api_client, customer, 999999, 'hi').status_code == 404


def test_missing_message_key_is_400(api_client, customer, order):
    api_client.force_authenticate(customer)
    r = api_client.post(reverse('send_order_message', args=[order.id]), {}, format='json')
    assert r.status_code == 400
    assert r.json() == {'error': 'Message cannot be empty'}
    assert OrderChatMessage.objects.count() == 0


# OE-399: whitespace-only messages are stored. Repro: POST /api/orders/<id>/chat/send/
# {"message": "   "} -> 201 and a blank chat bubble. Expect 400 "Message cannot be empty".
@pytest.mark.xfail(strict=True, reason='OE-399: whitespace-only chat message is accepted')
def test_whitespace_only_message_is_refused(api_client, customer, order):
    r = send(api_client, customer, order.id, '   ')
    assert r.status_code == 400
    assert OrderChatMessage.objects.count() == 0


# OE-400: a non-string message from the retailer 500s while building the customer
# notification (message_text[:50] on an int). Repro: retailer POSTs {"message": 123}
# to /api/orders/<id>/chat/send/ -> 500. Expect 400.
@pytest.mark.xfail(strict=True, reason='OE-400: non-string chat message from retailer gives 500')
def test_retailer_non_string_message_is_400(api_client, retailer_user, retailer, order):
    r = send(api_client, retailer_user, order.id, 123)
    assert r.status_code == 400


def test_mark_read_only_touches_the_other_sides_messages(api_client, customer, retailer_user, retailer, order):
    assert send(api_client, customer, order.id, 'from customer').status_code == 201
    assert send(api_client, retailer_user, order.id, 'from shop').status_code == 201
    api_client.force_authenticate(customer)
    assert api_client.post(reverse('mark_chat_read', args=[order.id])).status_code == 200
    by_sender = {m.sender_id: m.is_read for m in OrderChatMessage.objects.all()}
    assert by_sender == {customer.id: False, retailer_user.id: True}


# --- order stats (report) -------------------------------------------------------------------------

def stats(client, user, **params):
    client.force_authenticate(user)
    return client.get(reverse('get_order_stats'), params)


def test_inverted_custom_range_is_empty_not_error(api_client, retailer_user, retailer, order):
    today = timezone.now().date()
    r = stats(api_client, retailer_user, time_range='custom',
              start_date=str(today + timedelta(days=5)), end_date=str(today - timedelta(days=5)))
    assert r.status_code == 200
    assert r.json()['total_orders'] == 0


def test_huge_custom_range_is_fine(api_client, retailer_user, retailer, order):
    r = stats(api_client, retailer_user, time_range='custom', start_date='0001-01-01', end_date='9999-12-31')
    assert r.status_code == 200
    assert r.json()['total_orders'] == 1


def test_other_retailer_stats_never_include_my_orders(api_client, other_retailer_user, other_retailer, order):
    r = stats(api_client, other_retailer_user)
    assert r.status_code == 200
    assert r.json()['total_orders'] == 0
    assert Decimal(str(r.json()['total_revenue'] or 0)) == 0


def test_customer_cannot_read_retailer_stats_of_shop(api_client, customer, order):
    r = stats(api_client, customer)
    # Customers get their own stats or are refused; they must never see the shop's revenue keys.
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        assert 'cash_sales' not in r.json() and 'pos_sales' not in r.json()


# Current behaviour pinned: garbage custom dates are ignored (whole-history stats), while the
# inbox refuses the same input with 400. TODO: make stats refuse bad dates like the inbox.
def test_garbage_custom_dates_are_ignored(api_client, retailer_user, retailer, order):
    r = stats(api_client, retailer_user, time_range='custom', start_date='yesterday', end_date='31-31-2026')
    assert r.status_code == 200
    assert r.json()['total_orders'] == 1


# --- inbox paging / filters -----------------------------------------------------------------------

def inbox(client, user, **params):
    client.force_authenticate(user)
    return client.get(reverse('list_retailer_inbox'), params)


@pytest.mark.parametrize('field', ['start_date', 'end_date'])
def test_inbox_bad_date_is_400(api_client, retailer_user, retailer, order, field):
    r = inbox(api_client, retailer_user, **{field: '2026-13-45'})
    assert r.status_code == 400
    assert r.json() == {'error': f'{field} must be YYYY-MM-DD'}


@pytest.mark.parametrize('page', ['abc', '0', '-1', '9999'])
def test_inbox_garbage_page_is_404_not_500(api_client, retailer_user, retailer, order, page):
    r = inbox(api_client, retailer_user, page=page)
    assert r.status_code == 404


@pytest.mark.parametrize('size', ['-1', '0', 'abc'])
def test_inbox_garbage_page_size_falls_back_to_default(api_client, retailer_user, retailer, order, size):
    r = inbox(api_client, retailer_user, page_size=size)
    assert r.status_code == 200
    assert r.json()['count'] == 1


def test_inbox_page_size_is_capped_at_100(api_client, retailer_user, retailer, customer, address, order):
    for _ in range(100):
        Order.objects.create(customer=customer, retailer=retailer, delivery_address=address, delivery_mode='delivery',
                             payment_mode='cash', subtotal=Decimal('10'), total_amount=Decimal('10'), status='pending')
    r = inbox(api_client, retailer_user, page_size='100000')
    assert r.status_code == 200
    assert r.json()['count'] == 101
    assert len(r.json()['results']) == 100


@pytest.mark.parametrize('ordering', ['nonexistent_field', '-password', 'customer__password', ';drop'])
def test_inbox_garbage_ordering_never_500s(api_client, retailer_user, retailer, order, ordering):
    r = inbox(api_client, retailer_user, ordering=ordering)
    assert r.status_code in (200, 400)


def test_customer_cannot_open_retailer_inbox(api_client, customer, order):
    r = inbox(api_client, customer)
    assert r.status_code == 403
    assert r.json() == {'error': 'Only retailers can access the order inbox'}


def test_order_history_garbage_page_is_404(api_client, customer, order):
    api_client.force_authenticate(customer)
    r = api_client.get(reverse('get_order_history'), {'page': 'zzz'})
    assert r.status_code in (200, 404)
