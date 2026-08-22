import pytest
from django.urls import reverse
from rest_framework import status
from decimal import Decimal
from unittest.mock import MagicMock, patch

from authentication.models import User
from retailers.models import RetailerProfile, RetailerOperatingHours, RetailerReview
from retailers.views import (
    RetailerPagination,
    _is_public_ip,
    _parse_bool,
    _state_filter_q,
)


def _make_retailer(username, shop_name, city, state, *, is_active=True, pincode='400001'):
    user = User.objects.create_user(
        username=username,
        email=f'{username}@test.com',
        password='TestPass123!',
        user_type='retailer',
        is_active=True,
    )
    return RetailerProfile.objects.create(
        user=user,
        shop_name=shop_name,
        address_line1='1 Test St',
        city=city,
        state=state,
        pincode=pincode,
        is_active=is_active,
    )


@pytest.mark.django_db
class TestRetailerProfileViews:
    def test_get_profile(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        url = reverse('get_retailer_profile')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['shop_name'] == retailer.shop_name

    def test_create_profile(self, api_client):
        from authentication.models import User
        new_retailer_user = User.objects.create_user(
            username="new_ret", email="nr@t.com", password="P", user_type="retailer"
        )
        api_client.force_authenticate(user=new_retailer_user)
        url = reverse('create_retailer_profile')
        data = {
            "shop_name": "New Shop",
            "address_line1": "Road 1",
            "city": "Mumbai",
            "state": "MH",
            "pincode": "400001"
        }
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        # Verify default operating hours were created
        profile = RetailerProfile.objects.get(user=new_retailer_user)
        assert RetailerOperatingHours.objects.filter(retailer=profile).count() == 7

    def test_update_profile(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        url = reverse('update_retailer_profile')
        data = {"shop_description": "Updated description"}
        response = api_client.patch(url, data)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['shop_description'] == "Updated description"


@pytest.mark.django_db
class TestRetailerListViews:
    def test_list_retailers_filtering(self, api_client, retailer):
        url = reverse('list_retailers')
        
        # City match
        response = api_client.get(url, {"city": "TestCity"})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['results']) == 1
        
        # Pincode mismatch
        response = api_client.get(url, {"pincode": "000000"})
        assert len(response.data['results']) == 0

    def test_list_operational_cities(self, api_client, retailer):
        url = reverse('list_operational_cities')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert 'results' in response.data
        assert any(
            c['city'] == retailer.city and c['state'] == retailer.state
            for c in response.data['results']
        )

    def test_list_operational_cities_distinct_active_pairs(self, api_client, retailer):
        _make_retailer('ret_pune', 'Pune Shop', 'Pune', 'MH')
        _make_retailer('ret_dup', 'Pune Dup', 'Pune', 'MH')

        url = reverse('list_operational_cities')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        results = response.data['results']
        pairs = {(c['city'], c['state']) for c in results}
        assert ('Pune', 'MH') in pairs
        assert (retailer.city, retailer.state) in pairs
        assert sum(1 for c in results if c['city'] == 'Pune' and c['state'] == 'MH') == 1

    def test_list_operational_cities_excludes_inactive(self, api_client):
        _make_retailer('ret_active', 'Active Shop', 'Pune', 'MH')
        _make_retailer('ret_inactive', 'Gone Shop', 'Jaipur', 'RJ', is_active=False)

        url = reverse('list_operational_cities')
        response = api_client.get(url)
        pairs = {(c['city'], c['state']) for c in response.data['results']}
        assert ('Pune', 'MH') in pairs
        assert ('Jaipur', 'RJ') not in pairs

    def test_list_operational_cities_excludes_blank_city_or_state(self, api_client):
        _make_retailer('ret_ok', 'Ok Shop', 'Surat', 'GJ')
        _make_retailer('ret_empty_city', 'No City', '', 'MH')
        _make_retailer('ret_empty_state', 'No State', 'Surat', '')
        # city/state are non-null CharFields; blank '' is the realistic empty case
        # (view also excludes isnull for defensive coverage)

        url = reverse('list_operational_cities')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        pairs = {(c['city'], c['state']) for c in response.data['results']}
        assert ('Surat', 'GJ') in pairs
        assert ('', 'MH') not in pairs
        assert ('Surat', '') not in pairs
        assert all(c.get('city') and c.get('state') for c in response.data['results'])

    def test_list_operational_cities_empty_when_none_qualify(self, api_client):
        _make_retailer('ret_only_inactive', 'Gone', 'Jaipur', 'RJ', is_active=False)
        _make_retailer('ret_blank', 'Blank', '', 'MH')

        url = reverse('list_operational_cities')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['results'] == []

    def test_list_retailers_state_alias_positive(self, api_client):
        mh_retailer = _make_retailer('ret_mh', 'MH Shop', 'Mumbai', 'MH')
        full_name_retailer = _make_retailer(
            'ret_maha', 'Maha Shop', 'Pune', 'Maharashtra'
        )
        other = _make_retailer('ret_rj', 'RJ Shop', 'Jaipur', 'RJ')
        url = reverse('list_retailers')

        response = api_client.get(url, {'state': 'Maharashtra'})
        assert response.status_code == status.HTTP_200_OK
        ids = {r['id'] for r in response.data['results']}
        assert mh_retailer.id in ids
        assert full_name_retailer.id in ids
        assert other.id not in ids

        response = api_client.get(url, {'state': 'MH'})
        ids = {r['id'] for r in response.data['results']}
        assert mh_retailer.id in ids
        assert full_name_retailer.id in ids
        assert other.id not in ids

    def test_list_retailers_city_iexact_positive(self, api_client):
        mh_retailer = _make_retailer('ret_mum', 'Mum Shop', 'Mumbai', 'MH')
        url = reverse('list_retailers')
        response = api_client.get(url, {'city': 'mumbai'})
        ids = {r['id'] for r in response.data['results']}
        assert mh_retailer.id in ids

    def test_list_retailers_wrong_city_returns_empty(self, api_client):
        _make_retailer('ret_mum2', 'Mum Shop', 'Mumbai', 'MH')
        url = reverse('list_retailers')
        response = api_client.get(url, {'city': 'Delhi'})
        assert response.status_code == status.HTTP_200_OK
        assert response.data['results'] == []

    def test_list_retailers_partial_city_does_not_match(self, api_client):
        _make_retailer('ret_mum3', 'Mum Shop', 'Mumbai', 'MH')
        url = reverse('list_retailers')
        response = api_client.get(url, {'city': 'Mum'})
        assert response.data['results'] == []

    def test_list_retailers_wrong_state_returns_empty(self, api_client):
        _make_retailer('ret_mh2', 'MH Shop', 'Mumbai', 'MH')
        url = reverse('list_retailers')
        response = api_client.get(url, {'state': 'Karnataka'})
        assert response.status_code == status.HTTP_200_OK
        assert response.data['results'] == []

    def test_list_retailers_unrelated_state_alias_no_false_match(self, api_client):
        mh_retailer = _make_retailer('ret_mh3', 'MH Shop', 'Mumbai', 'MH')
        url = reverse('list_retailers')
        # RJ / Rajasthan must not match Maharashtra retailers
        response = api_client.get(url, {'state': 'RJ'})
        ids = {r['id'] for r in response.data['results']}
        assert mh_retailer.id not in ids
        assert response.data['results'] == []

        response = api_client.get(url, {'state': 'Rajasthan'})
        assert response.data['results'] == []

    def test_list_retailers_distance(self, api_client, retailer):
        # Delhi
        retailer.latitude = Decimal("28.6139")
        retailer.longitude = Decimal("77.2090")
        retailer.delivery_radius = 20 # 20km
        retailer.save()
        
        url = reverse('list_retailers')
        
        # Near New Delhi (10km away)
        # 28.6139, 77.1090 is approx 9.7km away
        response = api_client.get(url, {"lat": 28.6139, "lng": 77.1090})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['results']) == 1
        
        # Far away (Mumbai)
        response = api_client.get(url, {"lat": 19.0760, "lng": 72.8777})
        assert len(response.data['results']) == 0

    def test_list_retailers_without_radius_filter_keeps_far_shops(self, api_client, retailer):
        # Delhi shop, small radius
        retailer.latitude = Decimal("28.6139")
        retailer.longitude = Decimal("77.2090")
        retailer.delivery_radius = 5
        retailer.save()

        url = reverse('list_retailers')
        # Mumbai user: far outside the 5km radius
        response = api_client.get(
            url,
            {"lat": 19.0760, "lng": 72.8777, "filter_by_radius": "false"},
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.data['results']
        assert len(results) == 1
        assert results[0]['id'] == retailer.id
        assert 1140 <= results[0]['distance'] <= 1160

    def test_list_retailers_without_radius_filter_keeps_shops_missing_coords(
        self, api_client, retailer
    ):
        retailer.latitude = None
        retailer.longitude = None
        retailer.save()

        url = reverse('list_retailers')
        response = api_client.get(
            url,
            {"lat": 28.6139, "lng": 77.2090, "filter_by_radius": "false"},
        )

        results = response.data['results']
        assert len(results) == 1
        assert results[0]['latitude'] is None
        assert results[0]['longitude'] is None
        assert results[0]['distance'] is None

    def test_list_retailers_radius_filter_on_by_default(self, api_client, retailer):
        retailer.latitude = Decimal("28.6139")
        retailer.longitude = Decimal("77.2090")
        retailer.delivery_radius = 5
        retailer.save()

        url = reverse('list_retailers')
        # Omitted flag must behave exactly like the pre-existing filtering.
        response = api_client.get(url, {"lat": 19.0760, "lng": 72.8777})
        assert response.data['results'] == []

    def test_list_retailers_exposes_coordinates(self, api_client, retailer):
        retailer.latitude = Decimal("28.6139")
        retailer.longitude = Decimal("77.2090")
        retailer.save()

        url = reverse('list_retailers')
        response = api_client.get(url)

        result = response.data['results'][0]
        assert float(result['latitude']) == pytest.approx(28.6139)
        assert float(result['longitude']) == pytest.approx(77.2090)

    def test_list_retailers_map_contract_matches_customer_client(self, api_client, retailer):
        """Keys and encodings the city map reads from GET /api/retailers/."""
        retailer.latitude = Decimal("28.6139")
        retailer.longitude = Decimal("77.2090")
        retailer.delivery_radius = 5
        retailer.save()

        url = reverse('list_retailers')
        response = api_client.get(
            url,
            {
                "city": retailer.city,
                "state": retailer.state,
                "lat": "28.6139",
                "lng": "77.2090",
                "filter_by_radius": "false",
                "page_size": "100",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert RetailerPagination.max_page_size == 100
        assert set(response.data.keys()) >= {'count', 'next', 'previous', 'results'}
        result = response.data['results'][0]
        for key in (
            'id', 'shop_name', 'shop_description', 'shop_image',
            'city', 'state', 'pincode', 'latitude', 'longitude',
            'average_rating', 'total_ratings',
            'offers_delivery', 'offers_pickup', 'delivery_radius',
            'minimum_order_amount', 'categories', 'distance',
            'is_currently_open', 'next_open_time',
        ):
            assert key in result
        # DecimalField JSON is a string; PositiveIntegerField is a number.
        assert isinstance(result['latitude'], str)
        assert isinstance(result['longitude'], str)
        assert isinstance(result['delivery_radius'], int)
        assert isinstance(result['minimum_order_amount'], str)
        assert isinstance(result['distance'], (int, float))
        assert result['distance'] == pytest.approx(0, abs=0.05)


class TestParseBool:
    def test_missing_value_uses_default(self):
        assert _parse_bool(None, default=True) is True
        assert _parse_bool('', default=False) is False

    def test_explicit_values_win_over_default(self):
        assert _parse_bool('false', default=True) is False
        assert _parse_bool('FALSE', default=True) is False
        assert _parse_bool('0', default=True) is False
        assert _parse_bool('true', default=False) is True
        assert _parse_bool(' yes ', default=False) is True

    def test_unrecognised_value_is_false(self):
        assert _parse_bool('maybe', default=True) is False


class TestStateFilterHelpers:
    @staticmethod
    def _iexact_values(q):
        values = set()

        def collect(node):
            if isinstance(node, tuple) and len(node) == 2 and node[0] == 'state__iexact':
                values.add(node[1])
            elif hasattr(node, 'children'):
                for child in node.children:
                    collect(child)

        collect(q)
        return values

    def test_state_filter_q_code_and_name_variants(self):
        maha = self._iexact_values(_state_filter_q('Maharashtra'))
        assert 'Maharashtra' in maha
        assert 'MH' in maha

        code = self._iexact_values(_state_filter_q('mh'))
        assert 'Maharashtra' in code
        # Original query string is kept; iexact makes case irrelevant vs DB "MH"
        assert 'mh' in code or 'MH' in code

    def test_is_public_ip_positive(self):
        assert _is_public_ip('8.8.8.8') is True
        assert _is_public_ip('1.2.3.4') is True

    def test_is_public_ip_rejects_private_loopback_link_local_malformed(self):
        assert _is_public_ip('127.0.0.1') is False
        assert _is_public_ip('192.168.1.1') is False
        assert _is_public_ip('10.0.0.1') is False
        assert _is_public_ip('169.254.1.1') is False  # link-local
        assert _is_public_ip('::1') is False
        assert _is_public_ip('not-an-ip') is False


@pytest.mark.django_db
class TestGeoEstimateView:
    NULL_GEO = {'city': None, 'state': None, 'pincode': None}

    def _mock_success_response(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'status': 'success',
            'city': 'Jaipur',
            'regionName': 'Rajasthan',
            'zip': '302001',
        }
        return mock_resp

    @patch('retailers.views.requests.get')
    def test_geo_estimate_success(self, mock_get, api_client):
        mock_get.return_value = self._mock_success_response()
        url = reverse('geo_estimate')
        response = api_client.get(url, REMOTE_ADDR='8.8.8.8')
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'city': 'Jaipur',
            'state': 'Rajasthan',
            'pincode': '302001',
        }
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert args[0] == 'http://ip-api.com/json/8.8.8.8'
        assert kwargs['params'] == {'fields': 'status,message,city,regionName,zip'}
        assert kwargs['timeout'] == 3

    @patch('retailers.views.requests.get')
    def test_geo_estimate_provider_non_success_returns_nulls(self, mock_get, api_client):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {'status': 'fail', 'message': 'private range'}
        mock_get.return_value = mock_resp

        url = reverse('geo_estimate')
        response = api_client.get(url, REMOTE_ADDR='8.8.8.8')
        assert response.status_code == status.HTTP_200_OK
        assert response.data == self.NULL_GEO

    @patch('retailers.views.requests.get')
    def test_geo_estimate_http_error_returns_nulls(self, mock_get, api_client):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.json.return_value = {'status': 'success', 'city': 'ShouldNotUse'}
        mock_get.return_value = mock_resp

        url = reverse('geo_estimate')
        response = api_client.get(url, REMOTE_ADDR='8.8.8.8')
        assert response.status_code == status.HTTP_200_OK
        assert response.data == self.NULL_GEO
        mock_resp.json.assert_not_called()

    @patch('retailers.views.requests.get')
    def test_geo_estimate_request_exception_returns_nulls(self, mock_get, api_client):
        mock_get.side_effect = Exception('network down')
        url = reverse('geo_estimate')
        response = api_client.get(url, REMOTE_ADDR='8.8.8.8')
        assert response.status_code == status.HTTP_200_OK
        assert response.data == self.NULL_GEO

    @patch('retailers.views.requests.get')
    def test_geo_estimate_malformed_json_returns_nulls(self, mock_get, api_client):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.side_effect = ValueError('No JSON object could be decoded')
        mock_get.return_value = mock_resp

        url = reverse('geo_estimate')
        response = api_client.get(url, REMOTE_ADDR='8.8.8.8')
        assert response.status_code == status.HTTP_200_OK
        assert response.data == self.NULL_GEO

    @patch('retailers.views.requests.get')
    def test_geo_estimate_private_loopback_link_local_not_in_url_path(
        self, mock_get, api_client
    ):
        mock_get.return_value = self._mock_success_response()
        url = reverse('geo_estimate')

        for private_ip in ('127.0.0.1', '192.168.0.10', '10.1.2.3', '169.254.10.20'):
            mock_get.reset_mock()
            response = api_client.get(url, REMOTE_ADDR=private_ip)
            assert response.status_code == status.HTTP_200_OK
            args, _kwargs = mock_get.call_args
            assert args[0] == 'http://ip-api.com/json/'
            assert private_ip not in args[0]

    @patch('retailers.views.requests.get')
    def test_geo_estimate_x_forwarded_for_public_ip(self, mock_get, api_client):
        mock_get.return_value = self._mock_success_response()
        url = reverse('geo_estimate')
        # Use a real public IP (TEST-NET 203.0.113.0/24 is is_reserved → treated as non-public)
        response = api_client.get(
            url,
            REMOTE_ADDR='10.0.0.1',
            HTTP_X_FORWARDED_FOR='8.8.4.4, 10.0.0.1',
        )
        assert response.status_code == status.HTTP_200_OK
        args, _ = mock_get.call_args
        assert args[0] == 'http://ip-api.com/json/8.8.4.4'


@pytest.mark.django_db
class TestRetailerSettingsViews:
    def test_update_operating_hours(self, api_client, retailer_user, retailer, operating_hours):
        api_client.force_authenticate(user=retailer_user)
        url = reverse('update_operating_hours')
        
        data = {
            "operating_hours": [
                {
                    "day_of_week": "monday",
                    "is_open": False
                }
            ]
        }
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        
        operating_hours.refresh_from_db()
        assert operating_hours.is_open is False


@pytest.mark.django_db
class TestRetailerReviewViews:
    def test_create_review(self, api_client, customer, retailer):
        api_client.force_authenticate(user=customer)
        url = reverse('create_retailer_review', kwargs={'retailer_id': retailer.id})
        data = {"rating": 5, "comment": "Excellent!"}
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert RetailerReview.objects.filter(retailer=retailer, customer=customer).exists()
