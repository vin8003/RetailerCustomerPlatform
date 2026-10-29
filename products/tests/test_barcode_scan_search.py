"""POS barcode scans take an exact, indexed lookup instead of the ranked smart search (PR #219)."""
from decimal import Decimal

import pytest
from django.core.cache import caches
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from products.models import Product, ProductBatch
from products.search import barcode_scan_queryset
from products.tests.test_search_category_name_oe291 import _make_category, _make_product, _make_retailer


@pytest.fixture(autouse=True)
def locmem_search_cache():
    config = {
        'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'},
        'search': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'scan-search'},
    }
    with override_settings(CACHES=config):
        caches['search'].clear()
        yield
        caches['search'].clear()


@pytest.fixture
def shop(api_client):
    owner, profile = _make_retailer('scan_owner', 'Scan Shop')
    api_client.force_authenticate(user=owner)
    return profile


def _ids(response):
    return [row['id'] for row in response.data['results']]


@pytest.mark.django_db
class TestBarcodeScanQueryset:
    def test_not_a_scanned_code_returns_none(self, shop):
        category = _make_category(shop, 'Grocery')
        _make_product(shop, category, 'Atta', barcode='8901234567890')
        base = Product.objects.filter(retailer=shop)

        for text in ['atta', '12345', '8901 234', '', None, '89012345678901234567890123456789012345678901234567890']:
            assert barcode_scan_queryset(base, text) is None

    def test_unknown_code_returns_none(self, shop):
        category = _make_category(shop, 'Grocery')
        _make_product(shop, category, 'Atta', barcode='8901234567890')

        assert barcode_scan_queryset(Product.objects.filter(retailer=shop), '9999999999') is None

    def test_exact_product_barcode_only(self, shop):
        category = _make_category(shop, 'Grocery')
        atta = _make_product(shop, category, 'Atta', barcode='8901234567890')
        _make_product(shop, category, 'Atta Big', barcode='89012345678901')

        hits = barcode_scan_queryset(Product.objects.filter(retailer=shop), '8901234567890')

        assert list(hits) == [atta]

    def test_batch_barcode(self, shop):
        category = _make_category(shop, 'Grocery')
        oil = _make_product(shop, category, 'Oil', barcode='1111111111', has_batches=True)
        ProductBatch.objects.create(
            product=oil, retailer=shop, batch_number='B1', barcode='2222222222',
            price=Decimal('10.00'), quantity=3, is_active=True,
        )

        hits = barcode_scan_queryset(Product.objects.filter(retailer=shop), '2222222222')

        assert list(hits) == [oil]

    def test_other_shops_product_is_not_found(self, shop):
        _, other = _make_retailer('scan_other', 'Other Shop')
        theirs = _make_product(other, _make_category(other, 'Misc'), 'Theirs', barcode='5555555555')

        assert barcode_scan_queryset(Product.objects.filter(retailer=shop), '5555555555') is None
        assert Product.objects.filter(pk=theirs.pk).exists()

    def test_a_product_matching_twice_is_returned_once(self, shop):
        category = _make_category(shop, 'Grocery')
        tea = _make_product(shop, category, 'Tea', barcode='3333333333', has_batches=True)
        for number in ('B1', 'B2'):
            ProductBatch.objects.create(
                product=tea, retailer=shop, batch_number=number, barcode='3333333333',
                price=Decimal('10.00'), quantity=1, is_active=True,
            )

        hits = barcode_scan_queryset(Product.objects.filter(retailer=shop), '3333333333')

        assert list(hits) == [tea]


@pytest.mark.django_db
class TestBarcodeScanEndpoints:
    def test_retailer_scan_returns_only_the_exact_product(self, api_client, shop):
        category = _make_category(shop, 'Grocery')
        atta = _make_product(shop, category, 'Atta', barcode='8901234567890')
        _make_product(shop, category, 'Atta Big', barcode='89012345678901')

        response = api_client.get(reverse('search_products'), {'search': '8901234567890'})

        assert response.status_code == 200
        assert _ids(response) == [atta.id]

    def test_scan_skips_the_ranked_search(self, api_client, shop, monkeypatch):
        category = _make_category(shop, 'Grocery')
        _make_product(shop, category, 'Atta', barcode='8901234567890')

        def boom(*args, **kwargs):
            raise AssertionError('smart search ran for an exact barcode')

        monkeypatch.setattr('products.views.smart_product_search', boom)

        response = api_client.get(reverse('search_products'), {'search': '8901234567890'})

        assert response.status_code == 200
        assert len(response.data['results']) == 1

    def test_partial_code_and_names_still_use_the_smart_search(self, api_client, shop):
        category = _make_category(shop, 'Grocery')
        _make_product(shop, category, 'Atta', barcode='8901234567890')

        partial = api_client.get(reverse('search_products'), {'search': '890123456'})
        by_name = api_client.get(reverse('search_products'), {'search': 'atta'})

        assert len(partial.data['results']) == 1
        assert len(by_name.data['results']) == 1

    def test_repeat_scan_is_served_from_the_cache(self, api_client, shop):
        category = _make_category(shop, 'Grocery')
        _make_product(shop, category, 'Atta', barcode='8901234567890')
        api_client.get(reverse('search_products'), {'search': '8901234567890'})

        with CaptureQueriesContext(connection) as queries:
            again = api_client.get(reverse('search_products'), {'search': '8901234567890'})

        assert len(again.data['results']) == 1
        assert not [q for q in queries if 'FROM "product"' in q['sql']]

    def test_public_scan_returns_the_exact_product(self, api_client, shop):
        category = _make_category(shop, 'Grocery')
        atta = _make_product(shop, category, 'Atta', barcode='8901234567890')
        _make_product(shop, category, 'Atta Big', barcode='89012345678901')
        api_client.force_authenticate(user=None)

        response = api_client.get(
            reverse('search_products_public', args=[shop.id]), {'search': '8901234567890'},
        )

        assert response.status_code == 200
        assert _ids(response) == [atta.id]
