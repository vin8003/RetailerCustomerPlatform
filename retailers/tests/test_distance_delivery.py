"""Distance-based delivery fees, radius discovery and the checkout quote."""
import json
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from customers.models import CustomerAddress
from retailers.delivery_pricing import (
    TierConfigError,
    haversine_km,
    normalize_tiers,
    quote_delivery,
)
from retailers.models import RetailerProfile

SHOP_LAT, SHOP_LNG = Decimal('28.61390000'), Decimal('77.20900000')
KM_PER_DEG_LAT = 6371 * 3.141592653589793 / 180  # ~111.195


def north_of_shop(km):
    """A point `km` straight north of the shop (haversine-exact along a meridian)."""
    return float(SHOP_LAT) + km / KM_PER_DEG_LAT, float(SHOP_LNG)


@pytest.fixture
def pinned_shop(retailer):
    retailer.latitude = SHOP_LAT
    retailer.longitude = SHOP_LNG
    retailer.offers_delivery = True
    retailer.delivery_radius = 10
    retailer.delivery_charge = Decimal('25.00')
    retailer.delivery_fee_mode = 'distance'
    retailer.delivery_fee_tiers = [
        {'up_to_km': '2.00', 'fee': '20.00'},
        {'up_to_km': '5.00', 'fee': '35.00'},
    ]
    retailer.delivery_fee_per_km = Decimal('8.00')
    retailer.save()
    return retailer


def test_north_of_shop_helper_is_exact():
    lat, lng = north_of_shop(3)
    assert haversine_km(SHOP_LAT, SHOP_LNG, lat, lng) == pytest.approx(3, abs=1e-6)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestQuoteDelivery:
    @pytest.mark.parametrize('km, fee, pricing', [
        (0.5, '20.00', 'tier'),
        (2.0, '20.00', 'tier'),       # band ends are inclusive
        (2.01, '35.00', 'tier'),
        (5.0, '35.00', 'tier'),
        (5.2, '43.00', 'per_km'),     # 1 started km past the last band
        (6.0, '43.00', 'per_km'),
        (7.5, '59.00', 'per_km'),     # 2.5 km over -> 3 km charged
        (10.0, '75.00', 'per_km'),    # exactly at the radius
    ])
    def test_tiers_then_per_km(self, pinned_shop, km, fee, pricing):
        quote = quote_delivery(pinned_shop, *north_of_shop(km))
        assert quote.deliverable
        assert quote.fee == Decimal(fee)
        assert quote.pricing == pricing

    def test_beyond_radius_is_not_deliverable(self, pinned_shop):
        quote = quote_delivery(pinned_shop, *north_of_shop(10.3))
        assert not quote.deliverable
        assert quote.distance_km == Decimal('10.30')
        assert '10 km' in quote.reason

    def test_last_tier_holds_without_per_km(self, pinned_shop):
        pinned_shop.delivery_fee_per_km = 0
        quote = quote_delivery(pinned_shop, *north_of_shop(8))
        assert quote.fee == Decimal('35.00')

    def test_per_km_only_counts_from_shop_on_top_of_delivery_charge(self, pinned_shop):
        pinned_shop.delivery_fee_tiers = []
        pinned_shop.delivery_fee_per_km = Decimal('5.00')
        quote = quote_delivery(pinned_shop, *north_of_shop(3.2))
        assert quote.fee == Decimal('45.00')  # 25 + 4 km x 5

    def test_free_delivery_threshold_still_applies(self, pinned_shop):
        pinned_shop.free_delivery_threshold = Decimal('500.00')
        below = quote_delivery(pinned_shop, *north_of_shop(3), order_total=Decimal('499.99'))
        at = quote_delivery(pinned_shop, *north_of_shop(3), order_total=Decimal('500.00'))
        assert below.fee == Decimal('35.00')
        assert at.fee == Decimal('0.00') and at.base_fee == Decimal('35.00')
        assert at.free_delivery_applied

    def test_missing_coordinates_fall_back_to_flat_charge(self, pinned_shop):
        quote = quote_delivery(pinned_shop, None, None)
        assert quote.deliverable
        assert quote.fee == Decimal('25.00')
        assert quote.pricing == 'fallback_flat'
        assert quote.distance_km is None

    def test_zero_zero_pin_counts_as_missing(self, pinned_shop):
        quote = quote_delivery(pinned_shop, 0, 0)
        assert quote.deliverable and quote.pricing == 'fallback_flat'

    def test_unpinned_shop_falls_back_to_flat(self, pinned_shop):
        pinned_shop.latitude = pinned_shop.longitude = None
        quote = quote_delivery(pinned_shop, *north_of_shop(50))
        assert quote.deliverable and quote.fee == Decimal('25.00')

    def test_flat_mode_keeps_flat_fee_but_checks_radius(self, pinned_shop):
        pinned_shop.delivery_fee_mode = 'flat'
        assert quote_delivery(pinned_shop, *north_of_shop(9)).fee == Decimal('25.00')
        assert not quote_delivery(pinned_shop, *north_of_shop(11)).deliverable

    def test_zero_radius_means_default_five_km(self, pinned_shop):
        pinned_shop.delivery_radius = 0
        assert quote_delivery(pinned_shop, *north_of_shop(4.9)).deliverable
        assert not quote_delivery(pinned_shop, *north_of_shop(5.1)).deliverable

    def test_no_delivery_offered(self, pinned_shop):
        pinned_shop.offers_delivery = False
        assert not quote_delivery(pinned_shop, *north_of_shop(1)).deliverable

    def test_repricing_skips_serviceability(self, pinned_shop):
        quote = quote_delivery(pinned_shop, *north_of_shop(12), check_serviceable=False)
        assert quote.deliverable and quote.fee == Decimal('91.00')  # 35 + 7 x 8


class TestNormalizeTiers:
    def test_sorts_and_formats(self):
        assert normalize_tiers([{'up_to_km': 5, 'fee': 30}, {'up_to_km': '1.5', 'fee': '10.5'}]) == [
            {'up_to_km': '1.50', 'fee': '10.50'},
            {'up_to_km': '5.00', 'fee': '30.00'},
        ]

    def test_accepts_json_string_and_blank(self):
        assert normalize_tiers('[{"up_to_km": 2, "fee": 0}]') == [{'up_to_km': '2.00', 'fee': '0.00'}]
        assert normalize_tiers('') == []
        assert normalize_tiers(None) == []

    @pytest.mark.parametrize('raw', [
        'nope',
        {'up_to_km': 1, 'fee': 1},
        [{'up_to_km': 0, 'fee': 10}],
        [{'up_to_km': 3, 'fee': -1}],
        [{'up_to_km': 'x', 'fee': 1}],
        [{'up_to_km': 'NaN', 'fee': 1}],
        [{'fee': 1}],
        [{'up_to_km': 2, 'fee': 10}, {'up_to_km': '2.00', 'fee': 20}],
        [{'up_to_km': i + 1, 'fee': 1} for i in range(11)],
    ])
    def test_rejects_bad_input(self, raw):
        with pytest.raises(TierConfigError):
            normalize_tiers(raw)


# ---------------------------------------------------------------------------
# Retailer panel settings
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestProfileDeliverySettings:
    def test_multipart_update_with_json_tiers(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.patch(
            reverse('update_retailer_profile'),
            {
                'delivery_fee_mode': 'distance',
                'delivery_fee_tiers': json.dumps([
                    {'up_to_km': 5, 'fee': 30}, {'up_to_km': 2, 'fee': 15},
                ]),
                'delivery_fee_per_km': '6.5',
                'delivery_radius': '8',
            },
            format='multipart',
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        retailer.refresh_from_db()
        assert retailer.delivery_fee_mode == 'distance'
        assert retailer.delivery_fee_tiers == [
            {'up_to_km': '2.00', 'fee': '15.00'},
            {'up_to_km': '5.00', 'fee': '30.00'},
        ]
        assert retailer.delivery_fee_per_km == Decimal('6.50')
        assert retailer.delivery_radius == 8
        assert response.data['delivery_fee_tiers'] == retailer.delivery_fee_tiers

    def test_json_update(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.patch(
            reverse('update_retailer_profile'),
            {'delivery_fee_mode': 'distance', 'delivery_fee_tiers': [{'up_to_km': 3, 'fee': 20}]},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        retailer.refresh_from_db()
        assert retailer.delivery_fee_tiers == [{'up_to_km': '3.00', 'fee': '20.00'}]

    def test_distance_mode_needs_a_tier_or_rate(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.patch(
            reverse('update_retailer_profile'), {'delivery_fee_mode': 'distance'}, format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'delivery_fee_tiers' in response.data

    def test_bad_tier_is_400(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.patch(
            reverse('update_retailer_profile'),
            {'delivery_fee_tiers': [{'up_to_km': -1, 'fee': 5}]},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'delivery_fee_tiers' in response.data

    def test_public_detail_exposes_config(self, api_client, pinned_shop):
        response = api_client.get(reverse('get_retailer_detail', args=[pinned_shop.id]))
        assert response.data['delivery_fee_mode'] == 'distance'
        assert response.data['delivery_fee_tiers'][0] == {'up_to_km': '2.00', 'fee': '20.00'}
        assert response.data['delivery_fee_per_km'] == '8.00'


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _shop(username, **kwargs):
    user = User.objects.create_user(
        username=username, email=f'{username}@test.com', password='x', user_type='retailer',
    )
    defaults = dict(
        user=user, shop_name=username, address_line1='1 Rd', city='TestCity',
        state='TestState', pincode='123456', is_active=True, is_verified=True,
        verification_status='approved',
    )
    defaults.update(kwargs)
    return RetailerProfile.objects.create(**defaults)


@pytest.mark.django_db
class TestRadiusDiscovery:
    def _names(self, api_client, params):
        response = api_client.get(reverse('list_retailers'), params)
        assert response.status_code == status.HTTP_200_OK
        return {row['shop_name'] for row in response.data['results']}

    def test_pinned_shops_listed_by_their_radius(self, api_client):
        _shop('near', latitude=SHOP_LAT, longitude=SHOP_LNG, delivery_radius=5)
        _shop('far_big_radius', latitude=Decimal('28.70390000'), longitude=SHOP_LNG,
              delivery_radius=15, city='OtherCity')  # ~10 km away, other city
        _shop('far_small_radius', latitude=Decimal('28.70390000'), longitude=SHOP_LNG,
              delivery_radius=3, serviceable_pincodes=['123456'])
        lat, lng = north_of_shop(1)
        names = self._names(api_client, {
            'city': 'TestCity', 'state': 'TestState', 'lat': lat, 'lng': lng,
            'user_pincode': '123456',
        })
        # Radius decides for pinned shops: city and serviceable pincodes no longer do.
        assert names == {'near', 'far_big_radius'}

    def test_unpinned_shops_fall_back_to_city_and_pincode(self, api_client):
        _shop('unpinned_same_city')
        _shop('unpinned_other_city', city='OtherCity')
        _shop('unpinned_other_pin', pincode='654321')
        lat, lng = north_of_shop(1)
        names = self._names(api_client, {
            'city': 'TestCity', 'state': 'TestState', 'lat': lat, 'lng': lng,
            'user_pincode': '123456',
        })
        assert names == {'unpinned_same_city'}

        # City only (no pincode known): the city decides, as before.
        names = self._names(api_client, {'city': 'TestCity', 'lat': lat, 'lng': lng})
        assert names == {'unpinned_same_city', 'unpinned_other_pin'}

    def test_coordinates_without_any_place_hide_unpinned_shops(self, api_client):
        _shop('unpinned')
        lat, lng = north_of_shop(1)
        assert self._names(api_client, {'lat': lat, 'lng': lng}) == set()

    def test_no_coordinates_keeps_city_listing(self, api_client):
        _shop('near', latitude=SHOP_LAT, longitude=SHOP_LNG, delivery_radius=1)
        _shop('elsewhere', city='OtherCity')
        assert self._names(api_client, {'city': 'TestCity'}) == {'near'}

    def test_list_rows_carry_distance_and_fee_estimate(self, api_client, pinned_shop):
        lat, lng = north_of_shop(3)
        response = api_client.get(reverse('list_retailers'), {'lat': lat, 'lng': lng})
        row = response.data['results'][0]
        assert row['distance'] == pytest.approx(3, abs=0.01)
        assert row['delivery_fee_estimate'] == '35.00'
        assert row['delivery_fee_mode'] == 'distance'

    def test_map_mode_lists_out_of_radius_shops(self, api_client, pinned_shop):
        lat, lng = north_of_shop(30)
        names = self._names(api_client, {
            'city': pinned_shop.city, 'lat': lat, 'lng': lng, 'filter_by_radius': 'false',
        })
        assert names == {pinned_shop.shop_name}


# ---------------------------------------------------------------------------
# Checkout quote endpoint
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDeliveryQuoteEndpoint:
    def _address(self, customer, km):
        lat, lng = north_of_shop(km) if km is not None else (None, None)
        return CustomerAddress.objects.create(
            customer=customer, title='Home', address_type='home', address_line1='1 St',
            city='TestCity', state='TestState', pincode='123456', latitude=lat, longitude=lng,
        )

    def test_saved_address(self, api_client, customer, pinned_shop):
        address = self._address(customer, 6)
        api_client.force_authenticate(user=customer)
        response = api_client.get(
            reverse('get_delivery_quote', args=[pinned_shop.id]),
            {'address_id': address.id, 'order_total': '100'},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data['deliverable'] is True
        assert response.data['delivery_fee'] == '43.00'
        assert response.data['distance_km'] == '6.00'
        assert response.data['pricing'] == 'per_km'

    def test_out_of_radius_address(self, api_client, customer, pinned_shop):
        address = self._address(customer, 12)
        api_client.force_authenticate(user=customer)
        response = api_client.get(
            reverse('get_delivery_quote', args=[pinned_shop.id]), {'address_id': address.id},
        )
        assert response.data['deliverable'] is False
        assert response.data['reason']

    def test_address_without_pin_uses_flat_fee(self, api_client, customer, pinned_shop):
        address = self._address(customer, None)
        api_client.force_authenticate(user=customer)
        response = api_client.get(
            reverse('get_delivery_quote', args=[pinned_shop.id]), {'address_id': address.id},
        )
        assert response.data['delivery_fee'] == '25.00'
        assert response.data['pricing'] == 'fallback_flat'

    def test_other_customers_address_is_404(self, api_client, customer, pinned_shop):
        other = User.objects.create_user(
            username='other_c', email='o@test.com', password='x', user_type='customer',
        )
        address = self._address(other, 1)
        api_client.force_authenticate(user=customer)
        response = api_client.get(
            reverse('get_delivery_quote', args=[pinned_shop.id]), {'address_id': address.id},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_address_needs_signed_in_customer(self, api_client, customer, pinned_shop):
        address = self._address(customer, 1)
        response = api_client.get(
            reverse('get_delivery_quote', args=[pinned_shop.id]), {'address_id': address.id},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_anonymous_coordinates(self, api_client, pinned_shop):
        lat, lng = north_of_shop(1)
        response = api_client.get(
            reverse('get_delivery_quote', args=[pinned_shop.id]), {'lat': lat, 'lng': lng},
        )
        assert response.data['delivery_fee'] == '20.00'

    def test_malformed_input_is_400(self, api_client, pinned_shop):
        response = api_client.get(
            reverse('get_delivery_quote', args=[pinned_shop.id]), {'lat': 'abc', 'lng': '1'},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unlisted_shop_is_404(self, api_client, pinned_shop):
        pinned_shop.verification_status = 'pending'
        pinned_shop.save()
        response = api_client.get(reverse('get_delivery_quote', args=[pinned_shop.id]))
        assert response.status_code == status.HTTP_404_NOT_FOUND
