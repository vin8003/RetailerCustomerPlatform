"""
Search cache flows (PR #219): real sale / restock / edit endpoints, cross-process sharing,
the facet scan cap, telemetry on both endpoints, and the cache module itself.
"""
import subprocess
import sys
from decimal import Decimal

import pytest
from django.core.cache import caches
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from products import views as product_views
from products.inventory_service import apply_stock_decrease, apply_stock_increase
from products.models import Product, SearchTelemetry
from products.search_cache import (
    SEARCH_CACHE_TTL,
    bump_search_cache,
    get_cached_search,
    search_cache_key,
    set_cached_search,
)
from products.tests.test_search_category_name_oe291 import (
    _make_brand,
    _make_category,
    _make_product,
    _make_retailer,
)


@pytest.fixture(autouse=True)
def locmem_search_cache():
    config = {
        'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'},
        'search': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'search-cache-flows',
        },
    }
    with override_settings(CACHES=config):
        caches['search'].clear()
        yield
        caches['search'].clear()


@pytest.fixture
def shop(api_client):
    owner, profile = _make_retailer('flow_owner', 'Flow Shop')
    api_client.force_authenticate(user=owner)
    return profile


def _search(client, query, **params):
    return client.get(reverse('search_products'), {'search': query, **params})


def _qty(response, product):
    row = next(r for r in response.data['results'] if r['id'] == product.id)
    return Decimal(str(row['quantity']))


def _price(response, product):
    row = next(r for r in response.data['results'] if r['id'] == product.id)
    return Decimal(str(row['price']))


def _pos_sale(client, product, quantity):
    return client.post(
        reverse('create_pos_order'),
        {
            'customer_name': 'Walk-in',
            'customer_mobile': '9988776655',
            'payment_mode': 'cash',
            'subtotal': float(product.price * quantity),
            'total_amount': float(product.price * quantity),
            'items': [{'product_id': product.id, 'quantity': float(quantity), 'unit_price': float(product.price)}],
        },
        format='json',
    )


# --- real endpoints --------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_pos_checkout_is_visible_on_the_next_search(api_client, shop):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Pos Sale Atta', quantity=Decimal('10'))
    assert _qty(_search(api_client, 'Pos Sale Atta'), product) == Decimal('10')

    assert _pos_sale(api_client, product, Decimal('4')).status_code == status.HTTP_201_CREATED

    assert _qty(_search(api_client, 'Pos Sale Atta'), product) == Decimal('6')


@pytest.mark.django_db(transaction=True)
def test_restock_is_visible_on_the_next_search(api_client, shop):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Restock Atta', quantity=Decimal('2'))
    assert _qty(_search(api_client, 'Restock Atta'), product) == Decimal('2')

    apply_stock_increase(product, Decimal('5'))

    assert _qty(_search(api_client, 'Restock Atta'), product) == Decimal('7')


@pytest.mark.django_db(transaction=True)
def test_cancelled_order_restock_shows_after_a_sale(api_client, shop):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Cancel Atta', quantity=Decimal('10'))
    _search(api_client, 'Cancel Atta')
    apply_stock_decrease(product, Decimal('3'))
    assert _qty(_search(api_client, 'Cancel Atta'), product) == Decimal('7')

    apply_stock_increase(product, Decimal('3'))

    assert _qty(_search(api_client, 'Cancel Atta'), product) == Decimal('10')


@pytest.mark.django_db(transaction=True)
def test_single_product_edit_endpoint_invalidates(api_client, shop):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Edit Atta')
    assert _price(_search(api_client, 'Edit Atta'), product) == Decimal('20')

    response = api_client.patch(reverse('update_product', args=[product.id]), {'price': '27.00'}, format='json')
    assert response.status_code == status.HTTP_200_OK

    assert _price(_search(api_client, 'Edit Atta'), product) == Decimal('27')


@pytest.mark.django_db(transaction=True)
def test_bulk_edit_endpoint_invalidates(api_client, shop):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Bulk Edit Atta')
    assert _price(_search(api_client, 'Bulk Edit Atta'), product) == Decimal('20')

    response = api_client.patch(
        reverse('bulk_update_products'),
        {'items': [{'id': product.id, 'price': '33.00'}]},
        format='json',
    )
    assert response.status_code == status.HTTP_200_OK

    assert _price(_search(api_client, 'Bulk Edit Atta'), product) == Decimal('33')


@pytest.mark.django_db(transaction=True)
def test_deleting_a_product_removes_it_from_the_next_search(api_client, shop):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Delete Atta')
    assert _search(api_client, 'Delete Atta').data['results']

    product.delete()

    assert _search(api_client, 'Delete Atta').data['results'] == []


@pytest.mark.django_db(transaction=True)
def test_deactivating_a_product_removes_it_from_the_next_search(api_client, shop):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Inactive Atta')
    assert _search(api_client, 'Inactive Atta').data['results']

    product.is_active = False
    product.save()

    assert _search(api_client, 'Inactive Atta').data['results'] == []


# --- cross-process ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_a_bump_from_another_process_invalidates_this_process(api_client, shop, tmp_path):
    config = {
        'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'},
        'search': {'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache', 'LOCATION': str(tmp_path)},
    }
    with override_settings(CACHES=config):
        product = _make_product(shop, _make_category(shop, 'Flour'), 'Xproc Atta', quantity=Decimal('10'))
        assert _qty(_search(api_client, 'Xproc Atta'), product) == Decimal('10')

        # Another worker sells 4 units straight in the database, then bumps the shop's version in
        # the shared directory. It shares nothing with this process except the cache directory.
        Product.objects.filter(pk=product.pk).update(quantity=Decimal('6'))
        script = (
            'import sys, time\n'
            'from django.conf import settings\n'
            'settings.configure()\n'
            'from django.core.cache.backends.filebased import FileBasedCache\n'
            'FileBasedCache(sys.argv[1], {}).set("search_ver_" + sys.argv[2], time.time_ns(), None)\n'
        )
        subprocess.run([sys.executable, '-c', script, str(tmp_path), str(shop.id)], check=True)

        assert _qty(_search(api_client, 'Xproc Atta'), product) == Decimal('6')


@pytest.mark.django_db(transaction=True)
def test_without_a_bump_the_cached_answer_is_served(api_client, shop, tmp_path):
    config = {
        'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'},
        'search': {'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache', 'LOCATION': str(tmp_path)},
    }
    with override_settings(CACHES=config):
        product = _make_product(shop, _make_category(shop, 'Flour'), 'Stale Atta', quantity=Decimal('10'))
        _search(api_client, 'Stale Atta')
        Product.objects.filter(pk=product.pk).update(quantity=Decimal('6'))  # no signal, no bump

        assert _qty(_search(api_client, 'Stale Atta'), product) == Decimal('10')


# --- facets and the scan cap -----------------------------------------------------------------

@pytest.mark.django_db
def test_scan_cap_limits_the_match_count_and_the_facets(api_client, shop, monkeypatch):
    monkeypatch.setattr(product_views, 'SEARCH_SCAN_CAP', 3)
    flour = _make_category(shop, 'Cap Flour')
    for i in range(5):
        _make_product(shop, flour, f'Cap Grain {i}')

    response = _search(api_client, 'Cap Grain', limit='2')

    assert len(response.data['results']) == 2
    assert [row['count'] for row in response.data['facets']['categories']] == [3]
    assert SearchTelemetry.objects.get(query='Cap Grain').result_count == 3


@pytest.mark.django_db
def test_below_the_cap_facets_are_exact(api_client, shop, monkeypatch):
    monkeypatch.setattr(product_views, 'SEARCH_SCAN_CAP', 1000)
    flour = _make_category(shop, 'Exact Flour')
    for i in range(7):
        _make_product(shop, flour, f'Exact Grain {i}')

    response = _search(api_client, 'Exact Grain', limit='2')

    assert [row['count'] for row in response.data['facets']['categories']] == [7]
    assert SearchTelemetry.objects.get(query='Exact Grain').result_count == 7


@pytest.mark.django_db
def test_facets_list_only_the_top_ten_and_skip_missing_brand_and_category(api_client, shop):
    for i in range(12):
        _make_product(shop, _make_category(shop, f'Top Cat {i}'), f'Top Grain {i}', brand=_make_brand(f'Top Brand {i}'))
    _make_product(shop, None, 'Top Grain bare')

    facets = _search(api_client, 'Top Grain').data['facets']

    assert len(facets['categories']) == 10
    assert len(facets['brands']) == 10
    assert all(row['category__id'] is not None for row in facets['categories'])


@pytest.mark.django_db
def test_without_a_search_term_facets_come_from_the_grouped_queries_and_nothing_is_cached(api_client, shop):
    flour = _make_category(shop, 'Plain Flour')
    for i in range(3):
        _make_product(shop, flour, f'Plain Grain {i}')

    response = api_client.get(reverse('search_products'))

    assert response.status_code == status.HTTP_200_OK
    assert {row['category__name']: row['count'] for row in response.data['facets']['categories']} == {'Plain Flour': 3}
    assert not SearchTelemetry.objects.exists()


@pytest.mark.django_db
def test_category_filter_applies_before_the_scan(api_client, shop):
    flour = _make_category(shop, 'Filter Flour')
    rice = _make_category(shop, 'Filter Rice')
    _make_product(shop, flour, 'Filter Grain A')
    _make_product(shop, rice, 'Filter Grain B')

    response = _search(api_client, 'Filter Grain', category=str(flour.id))

    assert [row['name'] for row in response.data['results']] == ['Filter Grain A']
    assert SearchTelemetry.objects.get(query='Filter Grain').result_count == 1


# --- telemetry and the public endpoint -------------------------------------------------------

@pytest.mark.django_db
def test_public_search_telemetry_counts_matches_and_cache_hits(api_client, shop):
    flour = _make_category(shop, 'Public Flour')
    for i in range(3):
        _make_product(shop, flour, f'Public Tele {i}')
    api_client.force_authenticate(user=None)
    url = reverse('search_products_public', args=[shop.id])

    first = api_client.get(url, {'search': 'Public Tele', 'limit': '2'})
    second = api_client.get(url, {'search': 'Public Tele', 'limit': '2'})

    assert first.data == second.data
    assert len(first.data['results']) == 2
    assert list(SearchTelemetry.objects.filter(query='Public Tele').values_list('result_count', flat=True)) == [3, 3]


@pytest.mark.django_db
def test_public_search_cache_is_per_shop(api_client, shop):
    _make_product(shop, _make_category(shop, 'Flour'), 'Shared Name Atta')
    other_owner, other = _make_retailer('flow_other', 'Flow Other')
    _make_product(other, _make_category(other, 'Flour'), 'Shared Name Atta')
    api_client.force_authenticate(user=None)

    mine = api_client.get(reverse('search_products_public', args=[shop.id]), {'search': 'Shared Name'})
    theirs = api_client.get(reverse('search_products_public', args=[other.id]), {'search': 'Shared Name'})

    assert [r['id'] for r in mine.data['results']] != [r['id'] for r in theirs.data['results']]


@pytest.mark.django_db
def test_search_still_works_when_the_cache_is_down(api_client, shop, monkeypatch):
    product = _make_product(shop, _make_category(shop, 'Flour'), 'Down Atta')

    def boom(*args, **kwargs):
        raise OSError('cache directory is not writable')

    store = caches['search']
    monkeypatch.setattr(type(store), 'get', boom)
    monkeypatch.setattr(type(store), 'set', boom)
    monkeypatch.setattr(type(store), 'add', boom)

    response = _search(api_client, 'Down Atta')

    assert response.status_code == status.HTTP_200_OK
    assert [row['id'] for row in response.data['results']] == [product.id]


# --- the cache module ------------------------------------------------------------------------

def test_key_ignores_case_and_extra_spaces_but_not_other_inputs():
    base = search_cache_key('retailer', 1, 'Tata  Atta', limit=50)
    assert base == search_cache_key('retailer', 1, ' tata atta ', limit=50)
    assert base != search_cache_key('public', 1, 'tata atta', limit=50)
    assert base != search_cache_key('retailer', 2, 'tata atta', limit=50)
    assert base != search_cache_key('retailer', 1, 'tata atta', limit=10)
    assert base != search_cache_key('retailer', 1, 'tata atta', limit=50, cost=True)


@pytest.mark.django_db
def test_version_is_stable_until_bumped(django_capture_on_commit_callbacks):
    first = search_cache_key('retailer', 9, 'rice', limit=50)
    assert first == search_cache_key('retailer', 9, 'rice', limit=50)

    with django_capture_on_commit_callbacks(execute=True):
        bump_search_cache(9)

    assert first != search_cache_key('retailer', 9, 'rice', limit=50)


@pytest.mark.django_db
def test_bump_waits_for_the_commit(django_capture_on_commit_callbacks):
    before = search_cache_key('retailer', 8, 'rice', limit=50)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        bump_search_cache(8)
    assert before == search_cache_key('retailer', 8, 'rice', limit=50)

    for callback in callbacks:
        callback()
    assert before != search_cache_key('retailer', 8, 'rice', limit=50)


@pytest.mark.django_db
def test_bump_without_a_shop_is_a_noop(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        bump_search_cache(None)
    assert callbacks == []


@pytest.mark.django_db
def test_one_shop_bump_leaves_other_shops_alone(django_capture_on_commit_callbacks):
    other = search_cache_key('retailer', 6, 'rice', limit=50)
    with django_capture_on_commit_callbacks(execute=True):
        bump_search_cache(5)
    assert other == search_cache_key('retailer', 6, 'rice', limit=50)


def test_get_and_set_round_trip_and_swallow_backend_errors(monkeypatch):
    key = search_cache_key('retailer', 4, 'rice', limit=50)
    assert get_cached_search(key) is None
    set_cached_search(key, {'payload': 1, 'total': 2})
    assert get_cached_search(key) == {'payload': 1, 'total': 2}

    store = caches['search']
    monkeypatch.setattr(type(store), 'get', lambda *a, **k: (_ for _ in ()).throw(OSError('down')))
    monkeypatch.setattr(type(store), 'set', lambda *a, **k: (_ for _ in ()).throw(OSError('down')))
    assert get_cached_search(key) is None
    set_cached_search(key, {'payload': 1})  # must not raise


def test_ttl_is_a_short_backstop():
    assert 0 < SEARCH_CACHE_TTL <= 60


def test_an_unreachable_cache_means_no_key_and_no_caching(monkeypatch):
    store = caches['search']
    monkeypatch.setattr(type(store), 'get', lambda *a, **k: (_ for _ in ()).throw(OSError('down')))

    assert search_cache_key('retailer', 3, 'rice', limit=50) is None
    assert get_cached_search(None) is None
    set_cached_search(None, {'payload': 1})  # must not raise


# --- remaining branches ----------------------------------------------------------------------

@pytest.mark.django_db
def test_category_by_name_filters_the_search(api_client, shop):
    flour = _make_category(shop, 'Named Flour')
    rice = _make_category(shop, 'Named Rice')
    _make_product(shop, flour, 'Named Grain A')
    _make_product(shop, rice, 'Named Grain B')

    response = _search(api_client, 'Named Grain', category='Named Flour')

    assert [row['name'] for row in response.data['results']] == ['Named Grain A']


@pytest.mark.django_db
def test_category_name_that_matches_nothing_returns_no_results(api_client, shop):
    _make_product(shop, _make_category(shop, 'Known Flour'), 'Unknown Cat Grain')

    response = _search(api_client, 'Unknown Cat Grain', category='no-such-category')

    assert response.status_code == status.HTTP_200_OK
    assert response.data['results'] == []
    assert SearchTelemetry.objects.get(query='Unknown Cat Grain').result_count == 0


@pytest.mark.django_db
def test_customers_cannot_use_the_retailer_search(api_client, customer):
    api_client.force_authenticate(user=customer)

    assert _search(api_client, 'anything').status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_a_retailer_without_a_profile_gets_404(api_client):
    from authentication.models import User

    user = User.objects.create_user(
        username='no_profile', email='no_profile@test.com', password='TestPass123!',
        user_type='retailer', is_active=True,
    )
    api_client.force_authenticate(user=user)

    assert _search(api_client, 'anything').status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_a_failing_bump_is_swallowed(monkeypatch, django_capture_on_commit_callbacks):
    store = caches['search']
    monkeypatch.setattr(type(store), 'set', lambda *a, **k: (_ for _ in ()).throw(OSError('down')))

    with django_capture_on_commit_callbacks(execute=True):
        bump_search_cache(12)  # must not raise


@pytest.mark.django_db
def test_batch_receiver_falls_back_to_the_product_when_the_batch_has_no_shop(shop, django_capture_on_commit_callbacks):
    from products.signals import bump_search_cache_on_batch_change

    product = _make_product(shop, _make_category(shop, 'Flour'), 'Fallback Atta')

    class BatchWithoutShop:
        retailer_id = None
        product_id = product.id

    before = search_cache_key('retailer', shop.id, 'rice', limit=50)
    with django_capture_on_commit_callbacks(execute=True):
        bump_search_cache_on_batch_change(sender=None, instance=BatchWithoutShop())

    assert before != search_cache_key('retailer', shop.id, 'rice', limit=50)
