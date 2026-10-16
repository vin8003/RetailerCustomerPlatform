"""Review fixes carried over into the backend bundle (RCP #186)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from products.models import Product, ProductBatch

# What public search may send to customers (#130). Retailer-only fields
# (saleable_quantity, margin_percent, fractional_children, group_variants,
# purchase_price) must not appear here.
PUBLIC_SEARCH_KEYS = {
    'id', 'name', 'price', 'discounted_price', 'original_price', 'unit', 'image',
    'category_name', 'brand_name', 'barcode', 'is_featured', 'is_active',
    'is_seasonal', 'is_available', 'is_in_stock', 'product_group',
    'track_inventory', 'quantity', 'has_batches', 'batches',
    'is_parent_bulk', 'parent_bulk_product', 'conversion_factor',
}


@pytest.mark.django_db
def test_public_search_payload_is_pinned(api_client, retailer, product, product2):
    Product.objects.filter(pk__in=[product.pk, product2.pk]).update(
        product_group='review-rice', purchase_price=Decimal('40.00')
    )
    res = api_client.get(
        reverse('search_products_public', args=[retailer.id]), {'search': 'Test'}
    )
    assert res.status_code == 200
    assert res.data['results']
    for row in res.data['results']:
        assert set(row) == PUBLIC_SEARCH_KEYS


@pytest.mark.django_db
def test_customer_list_omits_group_variants(api_client, retailer, product, product2):
    Product.objects.filter(pk__in=[product.pk, product2.pk]).update(product_group='review-rice')
    res = api_client.get(reverse('get_retailer_products_public', args=[retailer.id]))
    assert res.status_code == 200
    rows = res.data['results'] if isinstance(res.data, dict) else res.data
    assert rows
    assert all('group_variants' not in row for row in rows)
    # Customer grids read brand_name from this list (customer #25).
    assert {row['brand_name'] for row in rows} == {'TestBrand'}


@pytest.mark.django_db
def test_exact_barcode_ranks_before_substring_match(api_client, retailer, retailer_user, category):
    common = dict(retailer=retailer, category=category, price=Decimal('10.00'), quantity=5)
    Product.objects.create(name='A substring', barcode='8901234567890', **common)
    extra = Product.objects.create(name='B extra code', additional_barcodes=['123456'], **common)
    Product.objects.create(name='C extra longer', additional_barcodes=['91234567'], **common)
    api_client.force_authenticate(user=retailer_user)

    res = api_client.get(reverse('search_products'), {'search': '123456'})

    assert res.status_code == 200
    assert res.data['results'][0]['id'] == extra.id


@pytest.mark.django_db
def test_retailer_search_is_in_stock_ignores_expired_batches(api_client, retailer, retailer_user, category):
    product = Product.objects.create(
        retailer=retailer, category=category, name='Expired Milk', price=Decimal('30.00'),
        quantity=4, has_batches=True, track_inventory=True,
    )
    ProductBatch.objects.create(
        product=product, retailer=retailer, batch_number='OLD', quantity=4,
        price=Decimal('30.00'), expiry_date=timezone.localdate() - timedelta(days=2),
    )
    api_client.force_authenticate(user=retailer_user)

    res = api_client.get(reverse('search_products'), {'search': 'Expired Milk'})

    row = next(r for r in res.data['results'] if r['id'] == product.id)
    assert row['saleable_quantity'] == 0
    assert row['is_in_stock'] is False
