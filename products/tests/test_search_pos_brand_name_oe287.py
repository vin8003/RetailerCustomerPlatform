"""
OE-287 / F follow-on — brand_name on search + POS no_page.

Same value as list/detail Product.brand.name. No brand → null
(mirror list getter). Auth/tenancy unchanged. READ only.
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


def _make_product(retailer, category, name, brand=None, unit="piece", **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "brand": brand,
        "price": Decimal("20.00"),
        "purchase_price": Decimal("10.00"),
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": unit,
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


def _brand_pk_lookups(queries):
    hits = []
    for query in queries:
        sql = query["sql"].lower()
        if "from \"product_brand\"" not in sql and "from product_brand" not in sql:
            continue
        if " join " in sql:
            continue
        hits.append(query["sql"])
    return hits


@pytest.mark.django_db
class TestSearchPosBrandName:
    def test_search_and_pos_brand_name_matches_list_and_detail(self, api_client):
        owner, shop = _make_retailer("oe287_hit_own", "OE287 Brand Shop")
        category = _make_category(shop, "OE287 Brand Cat")
        aashirvaad = _make_brand("OE287 Aashirvaad")
        britannia = _make_brand("OE287 Britannia")
        atta = _make_product(shop, category, "OE287 Atta", brand=aashirvaad)
        biscuits = _make_product(shop, category, "OE287 Biscuits", brand=britannia)

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE287")
        atta_detail = _detail(api_client, atta.id)
        biscuits_detail = _detail(api_client, biscuits.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert atta_detail.status_code == status.HTTP_200_OK
        assert biscuits_detail.status_code == status.HTTP_200_OK

        for product, expected, detail in (
            (atta, "OE287 Aashirvaad", atta_detail.data),
            (biscuits, "OE287 Britannia", biscuits_detail.data),
        ):
            list_row = _row_by_id(listed.data, product.id)
            search_row = _row_by_id(search.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            assert "brand_name" in search_row
            assert "brand_name" in pos_row
            assert search_row["brand_name"] == expected
            assert pos_row["brand_name"] == expected
            assert search_row["brand_name"] == list_row["brand_name"]
            assert pos_row["brand_name"] == list_row["brand_name"]
            assert search_row["brand_name"] == detail["brand_name"]
            assert pos_row["brand_name"] == detail["brand_name"]

    def test_null_brand_is_null_like_list(self, api_client):
        owner, shop = _make_retailer("oe287_null_own", "OE287 Null Shop")
        category = _make_category(shop, "OE287 Null Cat")
        product = _make_product(shop, category, "OE287 Loose Rice", brand=None)
        assert product.brand_id is None

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE287 Loose")
        detail = _detail(api_client, product.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_row = _row_by_id(listed.data, product.id)
        search_row = _row_by_id(search.data, product.id)
        pos_row = _row_by_id(pos.data, product.id)
        assert list_row["brand_name"] is None
        assert search_row["brand_name"] is None
        assert pos_row["brand_name"] is None
        assert detail.data["brand_name"] is None

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe287_auth_own", "OE287 Auth Shop")
        category = _make_category(shop, "OE287 Auth Cat")
        _make_product(
            shop,
            category,
            "OE287 Auth Rice",
            brand=_make_brand("OE287 Auth Brand"),
        )
        customer = _make_customer("oe287_auth_cust")

        anon_pos = _pos(api_client)
        anon_search = _search(api_client, "OE287")
        assert anon_pos.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_pos = _pos(api_client)
        cust_search = _search(api_client, "OE287")
        assert cust_pos.status_code == status.HTTP_403_FORBIDDEN
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN

    def test_search_and_pos_stay_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe287_ten_a", "OE287 Tenant A")
        owner_b, shop_b = _make_retailer("oe287_ten_b", "OE287 Tenant B")
        cat_a = _make_category(shop_a, "OE287 A Cat")
        cat_b = _make_category(shop_b, "OE287 B Cat")
        brand_a = _make_brand("OE287 Brand A")
        brand_b = _make_brand("OE287 Brand B")
        product_a = _make_product(shop_a, cat_a, "OE287 A SKU", brand=brand_a)
        product_b = _make_product(shop_b, cat_b, "OE287 B SKU", brand=brand_b)

        api_client.force_authenticate(user=owner_b)
        pos = _pos(api_client)
        search = _search(api_client, "OE287")
        detail_a = _detail(api_client, product_a.id)

        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        pos_ids = {row["id"] for row in pos.data}
        search_ids = {row["id"] for row in search.data["results"]}
        assert product_a.id not in pos_ids
        assert product_a.id not in search_ids
        assert product_b.id in pos_ids
        assert product_b.id in search_ids
        assert _row_by_id(pos.data, product_b.id)["brand_name"] == "OE287 Brand B"
        assert _row_by_id(search.data, product_b.id)["brand_name"] == "OE287 Brand B"

    def test_public_catalog_unchanged(self, api_client):
        _owner, shop = _make_retailer("oe287_pub_own", "OE287 Public Shop")
        category = _make_category(shop, "OE287 Public Cat")
        product = _make_product(
            shop,
            category,
            "OE287 Public Milk",
            brand=_make_brand("OE287 Public Brand"),
            unit="liter",
        )

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "OE287 Public"},
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK
        row = _row_by_id(public.data, product.id)
        search_row = _row_by_id(public_search.data, product.id)
        assert row["brand_name"] == "OE287 Public Brand"
        assert search_row["brand_name"] == row["brand_name"]
        assert row["unit"] == "liter"
        assert "saleable_quantity" not in row
        assert "margin_percent" not in row
        assert "saleable_quantity" not in search_row
        assert "margin_percent" not in search_row

    def test_pos_keeps_oe286_unit(self, api_client):
        owner, shop = _make_retailer("oe287_unit_own", "OE287 Unit Shop")
        category = _make_category(shop, "OE287 Unit Cat")
        product = _make_product(
            shop,
            category,
            "OE287 Unit Atta",
            brand=_make_brand("OE287 Unit Brand"),
            unit="kg",
        )

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        listed = _list(api_client)
        assert pos.status_code == status.HTTP_200_OK
        assert listed.status_code == status.HTTP_200_OK
        pos_row = _row_by_id(pos.data, product.id)
        list_row = _row_by_id(listed.data, product.id)
        assert pos_row["unit"] == list_row["unit"] == "kg"
        assert pos_row["brand_name"] == list_row["brand_name"] == "OE287 Unit Brand"

    def test_pos_keeps_oe285_pack_identity(self, api_client):
        owner, shop = _make_retailer("oe287_pack_own", "OE287 Pack Shop")
        category = _make_category(shop, "OE287 Pack Cat")
        brand = _make_brand("OE287 Pack Brand")
        parent = _make_product(
            shop,
            category,
            "OE287 Case",
            brand=brand,
            unit="box",
            is_parent_bulk=True,
            price=Decimal("100.00"),
            purchase_price=Decimal("60.00"),
        )
        child = _make_product(
            shop,
            category,
            "OE287 Piece",
            brand=brand,
            unit="piece",
            parent_bulk_product=parent,
            conversion_factor=Decimal("0.1000"),
            price=Decimal("12.00"),
            purchase_price=Decimal("6.00"),
        )

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        search = _search(api_client, "OE287")
        parent_detail = _detail(api_client, parent.id)
        child_detail = _detail(api_client, child.id)

        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert parent_detail.status_code == status.HTTP_200_OK
        assert child_detail.status_code == status.HTTP_200_OK

        pos_parent = _row_by_id(pos.data, parent.id)
        pos_child = _row_by_id(pos.data, child.id)
        search_parent = _row_by_id(search.data, parent.id)
        search_child = _row_by_id(search.data, child.id)

        assert pos_parent["brand_name"] == parent_detail.data["brand_name"] == "OE287 Pack Brand"
        assert pos_child["brand_name"] == child_detail.data["brand_name"] == "OE287 Pack Brand"
        assert search_parent["brand_name"] == "OE287 Pack Brand"
        assert search_child["brand_name"] == "OE287 Pack Brand"
        assert pos_parent["is_parent_bulk"] is True
        assert pos_parent["parent_bulk_product"] is None
        assert pos_parent["conversion_factor"] is None
        assert pos_child["is_parent_bulk"] is False
        assert pos_child["parent_bulk_product"] == parent.id
        assert Decimal(str(pos_child["conversion_factor"])) == Decimal("0.1000")
        assert search_parent["is_parent_bulk"] is True
        assert search_child["parent_bulk_product"] == parent.id

    def test_search_and_pos_join_brand_not_per_row(self, api_client):
        owner, shop = _make_retailer("oe287_q_own", "OE287 Query Shop")
        category = _make_category(shop, "OE287 Query Cat")
        products = []
        for i in range(3):
            brand = _make_brand(f"OE287 Query Brand {i}")
            products.append(
                _make_product(
                    shop,
                    category,
                    f"OE287 Query SKU {i}",
                    brand=brand,
                )
            )

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as search_ctx:
            search = _search(api_client, "OE287 Query")
        with CaptureQueriesContext(connection) as pos_ctx:
            pos = _pos(api_client)

        assert search.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert _brand_pk_lookups(search_ctx.captured_queries) == []
        assert _brand_pk_lookups(pos_ctx.captured_queries) == []
        for product in products:
            assert _row_by_id(search.data, product.id)["brand_name"] == product.brand.name
            assert _row_by_id(pos.data, product.id)["brand_name"] == product.brand.name
