"""
OE-106 / F-0023 — store vs owned-app price (thin EXTEND).

Phase 1: Product.app_price + resolve helper. Null falls back to store price.
One ATP pool is unchanged. No PriceList / marketplace connector.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from products.channel_price import (
    CHANNEL_APP,
    CHANNEL_STORE,
    app_price_summary,
    apply_channel_price_representation,
    create_payload_sets_app_price,
    format_money,
    payload_sets_app_price,
    price_channel_from_request,
    resolve_channel_price,
    submitted_app_price_differs,
)


def _product(store='40.00', app=None):
    return SimpleNamespace(
        id=1,
        price=Decimal(store),
        app_price=None if app is None else Decimal(app),
    )


class TestResolveChannelPrice:
    def test_null_app_price_falls_back_to_store(self):
        product = _product('40.00')
        assert resolve_channel_price(product, CHANNEL_STORE) == Decimal('40.00')
        assert resolve_channel_price(product, CHANNEL_APP) == Decimal('40.00')

    def test_app_price_can_differ_from_store(self):
        product = _product('40.00', app='35.50')
        assert resolve_channel_price(product, CHANNEL_STORE) == Decimal('40.00')
        assert resolve_channel_price(product, CHANNEL_APP) == Decimal('35.50')

    def test_store_channel_uses_batch_price(self):
        product = _product('40.00', app='30.00')
        batch = SimpleNamespace(price=Decimal('42.00'))
        assert resolve_channel_price(product, CHANNEL_STORE, batch=batch) == Decimal(
            '42.00'
        )
        assert resolve_channel_price(product, CHANNEL_APP, batch=batch) == Decimal(
            '30.00'
        )

    def test_app_without_override_uses_batch_then_store(self):
        product = _product('40.00')
        batch = SimpleNamespace(price=Decimal('42.00'))
        assert resolve_channel_price(product, CHANNEL_APP, batch=batch) == Decimal(
            '42.00'
        )


class TestPriceChannelFromRequest:
    def test_missing_request_is_app(self):
        assert price_channel_from_request(None) == CHANNEL_APP

    def test_customer_is_app(self):
        request = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, user_type='customer')
        )
        assert price_channel_from_request(request) == CHANNEL_APP

    def test_retailer_is_store(self):
        request = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, user_type='retailer')
        )
        assert price_channel_from_request(request) == CHANNEL_STORE


class TestAppPricePayloadHelpers:
    def test_detect_app_price_key(self):
        assert payload_sets_app_price({'app_price': '9.00'}) is True
        assert payload_sets_app_price({'price': '9.00'}) is False

    def test_echo_is_not_a_change(self):
        product = _product('40.00', app='35.00')
        assert submitted_app_price_differs(product, {'app_price': '35.00'}) is False
        assert submitted_app_price_differs(product, {'app_price': '36.00'}) is True
        assert submitted_app_price_differs(product, {'price': '41.00'}) is False

    def test_clearing_app_price_is_a_change(self):
        product = _product('40.00', app='35.00')
        assert submitted_app_price_differs(product, {'app_price': None}) is True

    def test_create_sets_app_price_only_when_value_present(self):
        assert create_payload_sets_app_price({'app_price': '12.00'}) is True
        assert create_payload_sets_app_price({'app_price': None}) is False
        assert create_payload_sets_app_price({'price': '12.00'}) is False


class TestChannelRepresentation:
    def test_app_channel_hides_store_list_and_app_price_field(self):
        product = _product('40.00', app='33.00')
        data = {
            'price': format_money(product.price),
            'discounted_price': format_money(product.price),
            'app_price': format_money(product.app_price),
        }
        apply_channel_price_representation(
            data, product, {'price_channel': CHANNEL_APP}
        )
        assert data['price'] == '33.00'
        assert data['discounted_price'] == '33.00'
        assert 'app_price' not in data

    def test_store_channel_keeps_store_price_and_exposes_app_price(self):
        product = _product('40.00', app='33.00')
        data = {'price': format_money(product.price)}
        apply_channel_price_representation(
            data, product, {'price_channel': CHANNEL_STORE}
        )
        assert data['price'] == '40.00'
        assert data['app_price'] == '33.00'


class TestAppPriceSummary:
    def test_explicit_none_is_not_current_product_value(self):
        product = _product('40.00', app='33.00')
        before = app_price_summary(product, app_price=None)
        after = app_price_summary(product)
        assert before['app_price'] is None
        assert after['app_price'] == '33.00'


@pytest.mark.django_db
class TestProductAppPriceField:
    def test_channel_selling_price_and_one_quantity_pool(self):
        from authentication.models import User
        from products.models import Product
        from retailers.models import RetailerProfile

        user = User.objects.create_user(
            username='oe106_p1',
            email='oe106_p1@test.com',
            password='TestPass123!',
            user_type='retailer',
            is_active=True,
        )
        shop = RetailerProfile.objects.create(
            user=user,
            shop_name='OE106 P1 Shop',
            address_line1='1 Main',
            city='City',
            state='State',
            pincode='110001',
            is_active=True,
        )
        product = Product.objects.create(
            retailer=shop,
            name='OE106 Rice',
            price=Decimal('40.00'),
            app_price=Decimal('33.00'),
            quantity=Decimal('7.000'),
            track_inventory=True,
            is_active=True,
            is_available=True,
            unit='kg',
        )
        assert product.channel_selling_price(CHANNEL_STORE) == Decimal('40.00')
        assert product.channel_selling_price(CHANNEL_APP) == Decimal('33.00')
        product.app_price = None
        product.save(update_fields=['app_price'])
        product.refresh_from_db()
        assert product.app_price is None
        assert product.channel_selling_price(CHANNEL_APP) == Decimal('40.00')
        assert product.quantity == Decimal('7.000')


@pytest.mark.django_db
class TestProductSearchSerializerChannel:
    def _product(self, username):
        from authentication.models import User
        from products.models import Product
        from retailers.models import RetailerProfile

        user = User.objects.create_user(
            username=username,
            email=f'{username}@test.com',
            password='TestPass123!',
            user_type='retailer',
            is_active=True,
        )
        shop = RetailerProfile.objects.create(
            user=user,
            shop_name='OE106 Search Ser Shop',
            address_line1='1 Main',
            city='City',
            state='State',
            pincode='110001',
            is_active=True,
        )
        return Product.objects.create(
            retailer=shop,
            name='OE106 Search Ser',
            price=Decimal('40.00'),
            app_price=Decimal('33.00'),
            quantity=Decimal('1.000'),
            track_inventory=True,
            is_active=True,
            is_available=True,
            unit='kg',
        )

    def test_missing_context_fail_closes_to_app(self):
        from products.serializers import ProductSearchSerializer

        data = ProductSearchSerializer(self._product('oe106_search_none')).data
        assert data['price'] == '33.00'
        assert 'app_price' not in data

    def test_retailer_request_keeps_store_and_app_price(self):
        from products.serializers import ProductSearchSerializer

        request = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, user_type='retailer')
        )
        data = ProductSearchSerializer(
            self._product('oe106_search_ret'), context={'request': request}
        ).data
        assert data['price'] == '40.00'
        assert data['app_price'] == '33.00'
