"""Order placement and modification price delivery with the checkout quote."""
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from orders.models import Order

SHOP_LAT, SHOP_LNG = Decimal('28.61390000'), Decimal('77.20900000')
KM_PER_DEG_LAT = 6371 * 3.141592653589793 / 180


def _pin(obj, km):
    obj.latitude = Decimal(str(round(float(SHOP_LAT) + km / KM_PER_DEG_LAT, 8)))
    obj.longitude = SHOP_LNG
    obj.save()


@pytest.fixture
def distance_shop(retailer):
    retailer.latitude = SHOP_LAT
    retailer.longitude = SHOP_LNG
    retailer.delivery_radius = 8
    retailer.delivery_charge = Decimal('25.00')
    retailer.delivery_fee_mode = 'distance'
    retailer.delivery_fee_tiers = [
        {'up_to_km': '2.00', 'fee': '20.00'},
        {'up_to_km': '5.00', 'fee': '35.00'},
    ]
    retailer.delivery_fee_per_km = Decimal('10.00')
    retailer.save()
    return retailer


@pytest.fixture
def verified_customer(customer):
    customer.is_phone_verified = True
    customer.save()
    return customer


def _place(api_client, customer, retailer, address):
    api_client.force_authenticate(user=customer)
    return api_client.post(reverse('place_order'), {
        'retailer_id': retailer.id,
        'delivery_mode': 'delivery',
        'payment_mode': 'cash',
        'address_id': address.id,
    })


@pytest.mark.django_db
@patch('common.notifications.send_push_notification')
@patch('common.notifications.send_silent_update')
class TestPlaceOrderDistanceFee:
    def test_fee_matches_quote_endpoint(
        self, _silent, _push, api_client, verified_customer, distance_shop, address, cart_with_items
    ):
        _pin(address, 6.4)  # 1.4 km past the last band -> 2 km at 10
        api_client.force_authenticate(user=verified_customer)
        quote = api_client.get(
            reverse('get_delivery_quote', args=[distance_shop.id]),
            {'address_id': address.id, 'order_total': '250.00'},
        )
        assert quote.data['delivery_fee'] == '55.00'

        response = _place(api_client, verified_customer, distance_shop, address)
        assert response.status_code == status.HTTP_201_CREATED, response.data
        order = Order.objects.get(customer=verified_customer)
        assert order.delivery_fee == Decimal('55.00')
        assert order.total_amount == Decimal('305.00')  # 250 items + 55

    def test_inner_tier(
        self, _silent, _push, api_client, verified_customer, distance_shop, address, cart_with_items
    ):
        _pin(address, 1.2)
        response = _place(api_client, verified_customer, distance_shop, address)
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Order.objects.get(customer=verified_customer).delivery_fee == Decimal('20.00')

    def test_free_delivery_threshold_wins(
        self, _silent, _push, api_client, verified_customer, distance_shop, address, cart_with_items
    ):
        distance_shop.free_delivery_threshold = Decimal('200.00')
        distance_shop.save()
        _pin(address, 4)
        response = _place(api_client, verified_customer, distance_shop, address)
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Order.objects.get(customer=verified_customer).delivery_fee == Decimal('0.00')

    def test_outside_radius_is_refused(
        self, _silent, _push, api_client, verified_customer, distance_shop, address, cart_with_items
    ):
        _pin(address, 9)
        response = _place(api_client, verified_customer, distance_shop, address)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'address_id' in response.data
        assert not Order.objects.filter(customer=verified_customer).exists()

    def test_address_without_pin_uses_flat_charge(
        self, _silent, _push, api_client, verified_customer, distance_shop, address, cart_with_items
    ):
        assert address.latitude is None
        response = _place(api_client, verified_customer, distance_shop, address)
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Order.objects.get(customer=verified_customer).delivery_fee == Decimal('25.00')

    def test_flat_shop_unchanged(
        self, _silent, _push, api_client, verified_customer, retailer, address, cart_with_items
    ):
        retailer.delivery_charge = Decimal('30.00')
        retailer.save()
        response = _place(api_client, verified_customer, retailer, address)
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Order.objects.get(customer=verified_customer).delivery_fee == Decimal('30.00')

    def test_pickup_has_no_fee_and_no_radius_check(
        self, _silent, _push, api_client, verified_customer, distance_shop, address, cart_with_items
    ):
        _pin(address, 50)
        api_client.force_authenticate(user=verified_customer)
        response = api_client.post(reverse('place_order'), {
            'retailer_id': distance_shop.id,
            'delivery_mode': 'pickup',
            'payment_mode': 'cash_pickup',
        })
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Order.objects.get(customer=verified_customer).delivery_fee == Decimal('0.00')


@pytest.mark.django_db
class TestOrderDetailDeliveryFields:
    def test_detail_exposes_distance_fee_for_modify_preview(
        self, api_client, retailer_user, distance_shop, order
    ):
        _pin(order.delivery_address, 3)
        from orders.serializers import OrderDetailSerializer

        data = OrderDetailSerializer(order).data
        assert data['delivery_fee_before_free_delivery'] == '35.00'
        assert data['delivery_distance_km'] == '3.00'


@pytest.mark.django_db
class TestModifyOrderDistanceFee:
    def test_modify_reprices_from_order_address_even_outside_radius(
        self, api_client, retailer_user, distance_shop, order
    ):
        # The shop shrank its radius after accepting: the order keeps delivering,
        # priced by distance (7 km = 35 + 2 km x 10).
        _pin(order.delivery_address, 7)
        distance_shop.delivery_radius = 3
        distance_shop.save()
        item = order.items.get()
        api_client.force_authenticate(user=retailer_user)
        response = api_client.post(
            reverse('modify_order', args=[order.id]),
            {'items': [{'id': item.id, 'quantity': 1}]},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        order.refresh_from_db()
        assert order.delivery_fee == Decimal('55.00')
