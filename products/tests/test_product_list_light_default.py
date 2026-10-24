"""Product list/search stay light by default and do not query per row.

Pins the default row keys of the retailer list, that group_variants is opt-in
(``include_group_variants=true``) on the list and search, and that the number of
queries does not grow with the number of rows (reviews, wishlist, batches).
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from customers.models import CustomerWishlist
from products.models import Product, ProductBatch, ProductReview
from products.tests.test_group_variants_reads_oe192 import (
    _make_category,
    _make_customer,
    _make_group,
    _make_product,
    _make_retailer,
)

RETAILER_LIST_KEYS = {
    "id", "name", "description", "price", "app_price", "purchase_price",
    "discounted_price", "original_price", "discount_percentage", "quantity",
    "saleable_quantity", "margin_percent", "track_inventory", "unit",
    "minimum_order_quantity", "maximum_order_quantity", "image", "image_url",
    "category_name", "brand_name", "retailer_name", "is_in_stock", "is_featured",
    "is_active", "is_seasonal", "is_available", "average_rating", "review_count",
    "created_at", "product_group", "active_offer_text", "is_wishlisted",
    "barcode", "has_batches", "batches", "is_parent_bulk", "parent_bulk_product",
    "conversion_factor", "fractional_children", "hsn_code", "gst_rate",
}


def _seed(shop, category, customer, n, prefix="Light"):
    products = []
    for i in range(n):
        product = _make_product(
            shop, category, f"{prefix} {i}", has_batches=(i % 2 == 0)
        )
        if product.has_batches:
            ProductBatch.objects.create(
                product=product, retailer=shop, batch_number=f"B{i}",
                price=Decimal("20.00"), original_price=Decimal("25.00"),
                quantity=Decimal("4.000"), is_active=True,
            )
        ProductReview.objects.create(product=product, customer=customer, rating=4)
        products.append(product)
    return products


@pytest.mark.django_db
class TestLightDefault:
    def test_retailer_list_row_contract_without_group_variants(self, api_client):
        owner, shop = _make_retailer("light_own", "Light Shop")
        category = _make_category(shop, "Light Cat")
        _make_group(shop, category, "Light Rice", "light-rice")
        api_client.force_authenticate(user=owner)

        listed = api_client.get(reverse("get_retailer_products"))
        assert listed.status_code == 200
        for row in listed.data["results"]:
            assert set(row) == RETAILER_LIST_KEYS

    def test_group_variants_opt_in_on_list_and_search(self, api_client):
        owner, shop = _make_retailer("light_opt_own", "Light Opt Shop")
        category = _make_category(shop, "Light Opt Cat")
        _make_group(shop, category, "Light Opt", "light-opt")
        api_client.force_authenticate(user=owner)

        for name in ("get_retailer_products", "search_products"):
            plain = api_client.get(reverse(name))
            asked = api_client.get(reverse(name), {"include_group_variants": "true"})
            rows = plain.data["results"]
            assert rows and all("group_variants" not in row for row in rows)
            assert all(len(row["group_variants"]) == 1 for row in asked.data["results"])

    def test_retailer_list_query_count_is_flat(self, api_client):
        owner, shop = _make_retailer("light_q_own", "Light Q Shop")
        category = _make_category(shop, "Light Q Cat")
        customer = _make_customer("light_q_cust")
        _seed(shop, category, customer, 2)
        api_client.force_authenticate(user=owner)
        url = reverse("get_retailer_products")
        api_client.get(url)  # warm caches that are not per request

        with CaptureQueriesContext(connection) as small:
            api_client.get(url)
        for i in range(10):
            p = _make_product(shop, category, f"Light more {i}", has_batches=True)
            ProductBatch.objects.create(
                product=p, retailer=shop, batch_number="M", price=Decimal("5.00"),
                original_price=Decimal("6.00"), quantity=Decimal("1.000"),
                is_active=True,
            )
            ProductReview.objects.create(product=p, customer=customer, rating=5)
        with CaptureQueriesContext(connection) as large:
            api_client.get(url)

        assert len(large) == len(small)

    def test_customer_list_values_and_flat_queries(self, api_client):
        _owner, shop = _make_retailer("light_c_own", "Light C Shop")
        shop.is_verified = True
        shop.verification_status = "approved"
        shop.save()
        category = _make_category(shop, "Light C Cat")
        customer = _make_customer("light_c_cust")
        products = _seed(shop, category, customer, 6)
        CustomerWishlist.objects.create(customer=customer, product=products[1])
        api_client.force_authenticate(user=customer)
        url = reverse("get_retailer_products_public", args=[shop.id])

        with CaptureQueriesContext(connection) as ctx:
            response = api_client.get(url)
        rows = {row["id"]: row for row in response.data["results"]}
        assert rows[products[1].id]["is_wishlisted"] is True
        assert rows[products[2].id]["is_wishlisted"] is False
        assert rows[products[0].id]["review_count"] == 1
        assert rows[products[0].id]["average_rating"] == 4
        assert len(rows[products[0].id]["batches"]) == 1
        assert rows[products[1].id]["batches"] == []
        assert all("group_variants" not in row for row in rows.values())

        for i in range(6):
            _seed(shop, category, customer, 1, prefix=f"Light extra {i}")
        with CaptureQueriesContext(connection) as bigger:
            api_client.get(url)
        assert len(bigger) == len(ctx)
