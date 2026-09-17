"""
OE-132 / F-0029 — saleable_quantity on retailer/POS product reads (thin EXTEND).

Gross Product.quantity stays unchanged. saleable_quantity uses the existing
helper (active, non-expired lots). Tenant-scoped. No ATP / holds.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductBatch, ProductCategory
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile


def _today():
    return timezone.localdate()


def _qty(val):
    return Decimal(str(val))


def _make_retailer(username, shop_name):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    profile = RetailerProfile.objects.create(
        user=user,
        shop_name=shop_name,
        address_line1="1 Main",
        city="City",
        state="State",
        pincode="110001",
        is_active=True,
    )
    ensure_organization_for_profile(profile, name=f"{shop_name} Org")
    return user, profile


def _make_customer(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
    )


def _make_category(retailer, name):
    return ProductCategory.objects.create(name=name, retailer=retailer)


def _make_batched_product(retailer, category, name):
    return Product.objects.create(
        retailer=retailer,
        name=name,
        category=category,
        price=Decimal("50.00"),
        has_batches=True,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="piece",
    )


def _make_simple_product(retailer, category, name, quantity):
    return Product.objects.create(
        retailer=retailer,
        name=name,
        category=category,
        price=Decimal("20.00"),
        quantity=quantity,
        has_batches=False,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="piece",
    )


def _make_batch(product, number, quantity, expiry=None, is_active=True):
    return ProductBatch.objects.create(
        product=product,
        retailer=product.retailer,
        batch_number=number,
        price=product.price,
        quantity=quantity,
        is_active=is_active,
        expiry_date=expiry,
    )


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _per_product_saleable_sums(queries):
    """Standalone SUM fired by Product.saleable_quantity() per product."""
    hits = []
    for query in queries:
        sql = query["sql"]
        lowered = sql.lower()
        if "sum(" not in lowered or "product_batch" not in lowered:
            continue
        if "expiry_date" not in lowered:
            continue
        if "saleable_quantity_annotated" in lowered:
            continue
        if ' as "total"' in lowered or " as total" in lowered:
            hits.append(sql)
    return hits


@pytest.mark.django_db
class TestSaleableQuantityRetailerReads:
    def test_pos_list_and_detail_exclude_expired_keep_gross(self, api_client):
        owner, shop = _make_retailer("oe132_pos_own", "OE132 POS Shop")
        category = _make_category(shop, "OE132 POS Cat")
        product = _make_batched_product(shop, category, "OE132 Milk")
        _make_batch(product, "EXP", 10, expiry=_today() - timedelta(days=1))
        _make_batch(product, "FRESH", 4, expiry=_today() + timedelta(days=5))
        _make_batch(product, "NULL", 2, expiry=None)
        product.sync_inventory_from_batches()
        product.refresh_from_db()
        assert product.quantity == Decimal("16.000")
        assert product.saleable_quantity() == Decimal("6.000")

        api_client.force_authenticate(user=owner)
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))
        search = api_client.get(
            reverse("search_products"), {"search": "OE132 Milk"}
        )

        assert pos.status_code == status.HTTP_200_OK
        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK

        pos_row = _row_by_id(pos.data, product.id)
        list_row = _row_by_id(listed.data, product.id)
        search_row = _row_by_id(search.data, product.id)

        for row in (pos_row, list_row, search_row, detail.data):
            assert _qty(row["quantity"]) == Decimal("16.000")
            assert _qty(row["saleable_quantity"]) == Decimal("6.000")

    def test_simple_sku_saleable_matches_gross(self, api_client):
        owner, shop = _make_retailer("oe132_simple_own", "OE132 Simple Shop")
        category = _make_category(shop, "OE132 Simple Cat")
        product = _make_simple_product(
            shop, category, "OE132 Dal", Decimal("9.000")
        )

        api_client.force_authenticate(user=owner)
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert pos.status_code == status.HTTP_200_OK
        row = _row_by_id(pos.data, product.id)
        assert _qty(row["quantity"]) == Decimal("9.000")
        assert _qty(row["saleable_quantity"]) == Decimal("9.000")

    def test_inactive_lot_stays_out_of_both(self, api_client):
        owner, shop = _make_retailer("oe132_inact_own", "OE132 Inactive Shop")
        category = _make_category(shop, "OE132 Inactive Cat")
        product = _make_batched_product(shop, category, "OE132 Oil")
        _make_batch(
            product, "DEAD", 7, expiry=_today() + timedelta(days=3), is_active=False
        )
        _make_batch(product, "FRESH", 3, expiry=_today() + timedelta(days=4))
        product.sync_inventory_from_batches()
        product.refresh_from_db()

        api_client.force_authenticate(user=owner)
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        row = _row_by_id(pos.data, product.id)
        assert _qty(row["quantity"]) == Decimal("3.000")
        assert _qty(row["saleable_quantity"]) == Decimal("3.000")

    def test_public_catalog_omits_saleable_quantity(self, api_client):
        owner, shop = _make_retailer("oe132_pub_own", "OE132 Public Shop")
        category = _make_category(shop, "OE132 Public Cat")
        product = _make_batched_product(shop, category, "OE132 Public Milk")
        _make_batch(product, "EXP", 8, expiry=_today() - timedelta(days=2))
        _make_batch(product, "FRESH", 5, expiry=_today() + timedelta(days=6))
        product.sync_inventory_from_batches()

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        assert public.status_code == status.HTTP_200_OK
        row = _row_by_id(public.data, product.id)
        assert "saleable_quantity" not in row
        assert _qty(row["quantity"]) == Decimal("13.000")

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("oe132_auth_own", "OE132 Auth Shop")
        category = _make_category(shop, "OE132 Auth Cat")
        product = _make_simple_product(
            shop, category, "OE132 Auth Rice", Decimal("2.000")
        )
        customer = _make_customer("oe132_auth_cust")

        anon_list = api_client.get(reverse("get_retailer_products"))
        anon_pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        anon_detail = api_client.get(
            reverse("get_product_detail", args=[product.id])
        )
        assert anon_list.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon_pos.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon_detail.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_list = api_client.get(reverse("get_retailer_products"))
        cust_detail = api_client.get(
            reverse("get_product_detail", args=[product.id])
        )
        assert cust_list.status_code == status.HTTP_403_FORBIDDEN
        assert cust_detail.status_code == status.HTTP_403_FORBIDDEN

    def test_no_cross_tenant_read(self, api_client):
        owner_a, shop_a = _make_retailer("oe132_ten_a", "OE132 Tenant A")
        owner_b, shop_b = _make_retailer("oe132_ten_b", "OE132 Tenant B")
        category_a = _make_category(shop_a, "OE132 A Cat")
        category_b = _make_category(shop_b, "OE132 B Cat")
        product_a = _make_batched_product(shop_a, category_a, "OE132 A Milk")
        product_b = _make_simple_product(
            shop_b, category_b, "OE132 B Wheat", Decimal("11.000")
        )
        _make_batch(product_a, "EXP", 10, expiry=_today() - timedelta(days=1))
        _make_batch(product_a, "FRESH", 4, expiry=_today() + timedelta(days=5))
        product_a.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner_b)
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(
            reverse("get_product_detail", args=[product_a.id])
        )
        search = api_client.get(
            reverse("search_products"), {"search": "OE132 A Milk"}
        )

        assert pos.status_code == status.HTTP_200_OK
        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code != status.HTTP_200_OK
        assert detail.data.get("id") != product_a.id
        assert search.status_code == status.HTTP_200_OK
        pos_ids = {row["id"] for row in pos.data}
        list_ids = {row["id"] for row in listed.data["results"]}
        search_ids = {row["id"] for row in search.data["results"]}
        assert product_a.id not in pos_ids
        assert product_a.id not in list_ids
        assert product_a.id not in search_ids
        assert product_b.id in pos_ids

    def test_pos_and_list_avoid_per_product_saleable_sum(self, api_client):
        owner, shop = _make_retailer("oe132_q_own", "OE132 Query Shop")
        category = _make_category(shop, "OE132 Query Cat")
        products = []
        for i in range(3):
            product = _make_batched_product(
                shop, category, f"OE132 Query Milk {i + 1}"
            )
            _make_batch(
                product, f"EXP{i}", 10, expiry=_today() - timedelta(days=1)
            )
            _make_batch(
                product, f"FRESH{i}", 4, expiry=_today() + timedelta(days=5)
            )
            product.sync_inventory_from_batches()
            products.append(product)

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as pos_ctx:
            pos = api_client.get(
                reverse("get_retailer_products"), {"no_page": "true"}
            )
        with CaptureQueriesContext(connection) as list_ctx:
            listed = api_client.get(reverse("get_retailer_products"))

        assert pos.status_code == status.HTTP_200_OK
        assert listed.status_code == status.HTTP_200_OK
        assert _per_product_saleable_sums(pos_ctx.captured_queries) == []
        assert _per_product_saleable_sums(list_ctx.captured_queries) == []
        for product in products:
            row = _row_by_id(pos.data, product.id)
            assert _qty(row["quantity"]) == Decimal("14.000")
            assert _qty(row["saleable_quantity"]) == Decimal("4.000")
