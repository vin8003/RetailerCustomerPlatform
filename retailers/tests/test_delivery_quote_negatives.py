"""Delivery-quote negatives beyond test_distance_delivery: half/odd coordinates, bad totals, bad ids."""
import pytest
from django.urls import reverse

from retailers.tests.test_distance_delivery import north_of_shop, pinned_shop  # noqa: F401  (fixture)


def quote(client, shop, **params):
    return client.get(reverse('get_delivery_quote', args=[shop.id]), params)


@pytest.mark.django_db
class TestDeliveryQuoteNegatives:
    def test_lat_without_lng_is_400(self, api_client, pinned_shop):
        r = quote(api_client, pinned_shop, lat='18.5')
        assert r.status_code == 400
        assert r.json() == {'lng': ['Must be a number.']}

    @pytest.mark.parametrize('lat', ['NaN', 'Infinity', 'abc'])
    def test_non_finite_lat_is_400(self, api_client, pinned_shop, lat):
        r = quote(api_client, pinned_shop, lat=lat, lng='73.8')
        assert r.status_code == 400
        assert r.json() == {'lat': ['Must be a number.']}

    # TODO(bug): lat/lng outside the globe are treated like "no pin" and quoted as
    # deliverable at the flat fee. Repro: GET /api/retailer/<id>/delivery-quote/?lat=999&lng=999
    # -> 200 {"deliverable": true, "delivery_fee": "25.00", "distance_km": null}. Expect 400.
    @pytest.mark.xfail(strict=True, reason='out-of-range coordinates quoted as deliverable')
    def test_off_planet_coordinates_are_refused(self, api_client, pinned_shop):
        r = quote(api_client, pinned_shop, lat='999', lng='999')
        assert r.status_code == 400 or r.json()['deliverable'] is False, r.json()

    def test_garbage_order_total_is_400(self, api_client, pinned_shop):
        lat, lng = north_of_shop(1)
        r = quote(api_client, pinned_shop, lat=lat, lng=lng, order_total='lots')
        assert r.status_code == 400
        assert r.json() == {'order_total': ['Must be a number.']}

    def test_negative_order_total_does_not_unlock_free_delivery(self, api_client, pinned_shop):
        pinned_shop.free_delivery_threshold = 100
        pinned_shop.save()
        lat, lng = north_of_shop(1)
        r = quote(api_client, pinned_shop, lat=lat, lng=lng, order_total='-500')
        assert r.status_code in (200, 400), r.content
        if r.status_code == 200:
            assert r.json()['delivery_fee'] == '20.00'

    @pytest.mark.parametrize('address_id', ['abc', '0', '-1'])
    def test_bad_address_id(self, api_client, customer, pinned_shop, address_id):
        api_client.force_authenticate(user=customer)
        r = quote(api_client, pinned_shop, address_id=address_id)
        assert r.status_code == 400
        assert 'address_id' in r.json()

    def test_unknown_shop_is_404(self, api_client):
        r = api_client.get(reverse('get_delivery_quote', args=[999999]))
        assert r.status_code == 404
