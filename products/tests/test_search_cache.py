"""
Search cache and one-pass search (PR #219).

The retailer and public product searches cache their response for a few seconds. Every stock or
price change must drop that entry, so a sale is visible on the next search. Telemetry records the
real match count, and facets count every match, not just the page that is returned.
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext, override_settings
from django.urls import reverse
from rest_framework import status

from products.inventory_service import apply_stock_decrease
from products.models import Product, ProductBatch, ProductCategory, SearchTelemetry
from products.search_cache import bump_search_cache
from products.tests.test_search_category_name_oe291 import (
    _make_brand,
    _make_category,
    _make_product,
    _make_retailer,
)

LOCMEM_SEARCH_CACHE = {
    'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'},
    'search': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'search-cache-tests',
    },
}


@pytest.fixture(autouse=True)
def search_cache():
    from django.core.cache import caches

    with override_settings(CACHES=LOCMEM_SEARCH_CACHE):
        caches['search'].clear()
        yield caches['search']
        caches['search'].clear()


def _search(client, query, **params):
    return client.get(reverse('search_products'), {'search': query, **params})


def _row(response, product):
    return next(row for row in response.data['results'] if row['id'] == product.id)


@pytest.fixture
def shop(api_client):
    owner, profile = _make_retailer('cache_owner', 'Cache Shop')
    api_client.force_authenticate(user=owner)
    return profile


@pytest.mark.django_db
def test_repeat_search_is_served_from_cache(api_client, shop):
    _make_product(shop, _make_category(shop, 'Flour'), 'Cache Atta 1kg')

    first = _search(api_client, 'Cache Atta')
    with CaptureQueriesContext(connection) as repeat:
        second = _search(api_client, 'Cache Atta')

    assert first.status_code == second.status_code == status.HTTP_200_OK
    assert second.data == first.data
    assert not [q for q in repeat.captured_queries if 'product"' in q['sql'].lower() and 'select' in q['sql'].lower()
                and 'telemetry' not in q['sql'].lower()]


@pytest.mark.django_db
def test_sale_is_visible_on_the_next_search(api_client, shop, django_capture_on_commit_callbacks):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Sale Atta 1kg')
    assert Decimal(str(_row(_search(api_client, 'Sale Atta'), product)['quantity'])) == Decimal('8')

    with django_capture_on_commit_callbacks(execute=True):
        apply_stock_decrease(product, Decimal('3'))  # the helper POS bills and online orders sell through

    assert Decimal(str(_row(_search(api_client, 'Sale Atta'), product)['quantity'])) == Decimal('5')


@pytest.mark.django_db
def test_price_edit_is_visible_on_the_next_search(api_client, shop, django_capture_on_commit_callbacks):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Price Atta 1kg')
    assert Decimal(str(_row(_search(api_client, 'Price Atta'), product)['price'])) == Decimal('20')

    with django_capture_on_commit_callbacks(execute=True):
        product.price = Decimal('25.00')
        product.save()

    assert Decimal(str(_row(_search(api_client, 'Price Atta'), product)['price'])) == Decimal('25')


@pytest.mark.django_db
def test_bulk_writes_that_skip_signals_bump_explicitly(api_client, shop, django_capture_on_commit_callbacks):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Bulk Atta 1kg')
    _search(api_client, 'Bulk Atta')

    with django_capture_on_commit_callbacks(execute=True):
        Product.objects.filter(pk=product.pk).update(price=Decimal('31.00'))
        bump_search_cache(shop.id)

    assert Decimal(str(_row(_search(api_client, 'Bulk Atta'), product)['price'])) == Decimal('31')


@pytest.mark.django_db
def test_batch_change_invalidates(api_client, shop, django_capture_on_commit_callbacks):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Batch Atta 1kg', has_batches=True)
    batch = ProductBatch.objects.create(
        product=product, retailer=shop, batch_number='B1', quantity=Decimal('4'), price=Decimal('20.00'),
    )
    _search(api_client, 'Batch Atta')

    with django_capture_on_commit_callbacks(execute=True):
        batch.price = Decimal('22.00')
        batch.save()

    response = _search(api_client, 'Batch Atta')
    assert response.status_code == status.HTTP_200_OK
    batches = _row(response, product)['batches']
    assert [Decimal(str(b['price'])) for b in batches] == [Decimal('22')]


@pytest.mark.django_db
def test_another_shops_change_does_not_clear_this_shop(api_client, shop, django_capture_on_commit_callbacks):
    _make_product(shop, _make_category(shop, 'Flour'), 'Iso Atta 1kg')
    _search(api_client, 'Iso Atta')
    _, other = _make_retailer('cache_other', 'Other Shop')

    with django_capture_on_commit_callbacks(execute=True):
        _make_product(other, _make_category(other, 'Flour'), 'Iso Other 1kg')

    with CaptureQueriesContext(connection) as repeat:
        _search(api_client, 'Iso Atta')
    assert not [q for q in repeat.captured_queries if '"product"' in q['sql'].lower() and 'telemetry' not in q['sql'].lower()]


@pytest.mark.django_db
def test_other_shops_never_see_this_shops_cached_results(api_client, shop):
    _make_product(shop, _make_category(shop, 'Flour'), 'Tenant Atta 1kg')
    assert _search(api_client, 'Tenant Atta').data['results']

    other_owner, _ = _make_retailer('cache_other2', 'Other Shop Two')
    api_client.force_authenticate(user=other_owner)
    assert _search(api_client, 'Tenant Atta').data['results'] == []


@pytest.mark.django_db
def test_telemetry_records_the_real_match_count_even_on_cache_hits(api_client, shop):
    category = _make_category(shop, 'Flour')
    for i in range(3):
        _make_product(shop, category, f'Telemetry Atta {i}')

    first = _search(api_client, 'Telemetry Atta', limit='2')
    second = _search(api_client, 'Telemetry Atta', limit='2')

    assert len(first.data['results']) == len(second.data['results']) == 2
    counts = list(SearchTelemetry.objects.filter(retailer=shop, query='Telemetry Atta').values_list('result_count', flat=True))
    assert counts == [3, 3]


@pytest.mark.django_db
def test_telemetry_records_zero_for_no_match(api_client, shop):
    _make_product(shop, _make_category(shop, 'Flour'), 'Zero Atta 1kg')
    _search(api_client, 'qqqzzz')
    assert list(SearchTelemetry.objects.filter(query='qqqzzz').values_list('result_count', flat=True)) == [0]


@pytest.mark.django_db
def test_facets_count_every_match_not_only_the_returned_page(api_client, shop):
    flour = _make_category(shop, 'Flour Facet')
    rice = _make_category(shop, 'Rice Facet')
    brand = _make_brand('Facet Brand')
    for i in range(3):
        _make_product(shop, flour, f'Facet Grain {i}', brand=brand)
    _make_product(shop, rice, 'Facet Grain rice', brand=brand)

    response = _search(api_client, 'Facet Grain', limit='1')

    assert len(response.data['results']) == 1
    categories = {row['category__name']: row['count'] for row in response.data['facets']['categories']}
    assert categories == {'Flour Facet': 3, 'Rice Facet': 1}
    assert response.data['facets']['brands'] == [
        {'brand__id': brand.id, 'brand__name': 'Facet Brand', 'count': 4}
    ]


@pytest.mark.django_db
def test_results_keep_relevance_order(api_client, shop):
    category = _make_category(shop, 'Order')
    _make_product(shop, category, 'Order Zeta Atta')
    exact = _make_product(shop, category, 'Order Atta')

    names = [row['name'] for row in _search(api_client, 'Order Atta').data['results']]
    assert names[0] == exact.name


@pytest.mark.django_db
def test_public_search_cache_is_cleared_by_a_sale(api_client, shop, django_capture_on_commit_callbacks):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Public Atta 1kg')
    url = reverse('search_products_public', args=[shop.id])
    api_client.force_authenticate(user=None)

    assert Decimal(str(api_client.get(url, {'search': 'Public Atta'}).data['results'][0]['quantity'])) == Decimal('8')
    with django_capture_on_commit_callbacks(execute=True):
        assert product.reduce_quantity(Decimal('2'))

    assert Decimal(str(api_client.get(url, {'search': 'Public Atta'}).data['results'][0]['quantity'])) == Decimal('6')
