"""
OE-291 / F follow-on — category_name on retailer search.

Same Product.category.name as list/detail. No category → list getter
sentinel (null), not POS Uncategorized. Public search shares the
serializer. Auth/tenancy unchanged. READ only.
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductBrand, ProductCategory
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8902911111111"


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


def _make_brand(name):
    return ProductBrand.objects.create(name=name, is_active=True)


def _make_product(retailer, category, name, brand=None, barcode=None, **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "brand": brand,
        "barcode": barcode,
        "price": Decimal("20.00"),
        "purchase_price": Decimal("10.00"),
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "piece",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _pos(api_client):
    return api_client.get(reverse("get_retailer_products"), {"no_page": "true"})


def _list(api_client):
    return api_client.get(reverse("get_retailer_products"))


def _detail(api_client, product_id):
    return api_client.get(reverse("get_product_detail", args=[product_id]))


def _search(api_client, query):
    return api_client.get(reverse("search_products"), {"search": query})


def _category_pk_lookups(queries):
    hits = []
    for query in queries:
        sql = query["sql"].lower()
        if "from \"product_category\"" not in sql and "from product_category" not in sql:
            continue
        if " join " in sql:
            continue
        hits.append(query["sql"])
    return hits


@pytest.mark.django_db
class TestSearchCategoryName:
    def test_search_category_name_matches_list_detail_and_pos(self, api_client):
        owner, shop = _make_retailer("oe291_hit_own", "OE291 Category Shop")
        groceries = _make_category(shop, "OE291 Groceries")
        snacks = _make_category(shop, "OE291 Snacks")
        aashirvaad = _make_brand("OE291 Aashirvaad")
        britannia = _make_brand("OE291 Britannia")
        atta = _make_product(
            shop, groceries, "OE291 Atta", brand=aashirvaad, barcode=PRIMARY_A
        )
        biscuits = _make_product(
            shop, snacks, "OE291 Biscuits", brand=britannia, barcode="8902912222222"
        )

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE291")
        atta_detail = _detail(api_client, atta.id)
        biscuits_detail = _detail(api_client, biscuits.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert atta_detail.status_code == status.HTTP_200_OK
        assert biscuits_detail.status_code == status.HTTP_200_OK

        for product, expected, detail in (
            (atta, "OE291 Groceries", atta_detail.data),
            (biscuits, "OE291 Snacks", biscuits_detail.data),
        ):
            list_row = _row_by_id(listed.data, product.id)
            search_row = _row_by_id(search.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            assert "category_name" in search_row
            assert search_row["category_name"] == expected
            assert search_row["category_name"] == list_row["category_name"]
            assert search_row["category_name"] == pos_row["category_name"]
            assert search_row["category_name"] == detail["category_name"]
            # OE-287 / OE-290 light non-regression.
            assert search_row["brand_name"] == list_row["brand_name"]
            assert search_row["brand_name"] == pos_row["brand_name"]
            assert search_row["barcode"] == list_row["barcode"]
            assert search_row["barcode"] == pos_row["barcode"]

    def test_null_category_mirrors_list_getter(self, api_client):
        owner, shop = _make_retailer("oe291_null_own", "OE291 Null Shop")
        loose = _make_product(shop, None, "OE291 Loose Rice", barcode=None)
        assert loose.category_id is None

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE291 Loose")
        detail = _detail(api_client, loose.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_row = _row_by_id(listed.data, loose.id)
        search_row = _row_by_id(search.data, loose.id)
        pos_row = _row_by_id(pos.data, loose.id)
        assert list_row["category_name"] is None
        assert detail.data["category_name"] is None
        assert search_row["category_name"] is None
        assert search_row["category_name"] == list_row["category_name"]
        assert search_row["category_name"] == detail.data["category_name"]
        # POS no_page already uses Uncategorized; do not retarget that row.
        assert pos_row["category_name"] == "Uncategorized"

    def test_public_search_category_name_matches_public_list(self, api_client):
        _owner, shop = _make_retailer("oe291_pub_own", "OE291 Public Shop")
        category = _make_category(shop, "OE291 Public Cat")
        branded = _make_product(
            shop,
            category,
            "OE291 Public Milk",
            brand=_make_brand("OE291 Public Brand"),
            barcode=PRIMARY_A,
        )
        loose = _make_product(shop, None, "OE291 Public Loose", barcode=None)

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "OE291 Public"},
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK

        branded_list = _row_by_id(public.data, branded.id)
        branded_search = _row_by_id(public_search.data, branded.id)
        loose_list = _row_by_id(public.data, loose.id)
        loose_search = _row_by_id(public_search.data, loose.id)
        assert branded_search["category_name"] == branded_list["category_name"]
        assert branded_search["category_name"] == "OE291 Public Cat"
        assert loose_search["category_name"] == loose_list["category_name"]
        assert loose_search["category_name"] is None
        # Shared serializer still echoes OE-287 / OE-290 fields.
        assert branded_search["brand_name"] == branded_list["brand_name"]
        assert branded_search["barcode"] == branded_list["barcode"] == PRIMARY_A

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe291_auth_own", "OE291 Auth Shop")
        category = _make_category(shop, "OE291 Auth Cat")
        _make_product(shop, category, "OE291 Auth Rice", barcode=PRIMARY_A)
        customer = _make_customer("oe291_auth_cust")

        anon_search = _search(api_client, "OE291")
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_search = _search(api_client, "OE291")
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN

    def test_search_joins_category_not_per_row(self, api_client):
        owner, shop = _make_retailer("oe291_q_own", "OE291 Query Shop")
        products = []
        for i in range(3):
            category = _make_category(shop, f"OE291 Query Cat {i}")
            products.append(
                _make_product(
                    shop,
                    category,
                    f"OE291 Query SKU {i}",
                    brand=_make_brand(f"OE291 Query Brand {i}"),
                )
            )

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as search_ctx:
            search = _search(api_client, "OE291 Query")

        assert search.status_code == status.HTTP_200_OK
        assert _category_pk_lookups(search_ctx.captured_queries) == []
        for product in products:
            assert (
                _row_by_id(search.data, product.id)["category_name"]
                == product.category.name
            )
