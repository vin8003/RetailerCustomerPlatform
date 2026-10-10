"""
OE-192 / F-0018 — group_variants on retailer list/search/POS no_page.

Thin EXTEND only. Same sibling shape as detail. Empty group → [].
Shop-scoped. No N+1. No size/color matrix generator.
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

VARIANT_KEYS = {
    "id",
    "name",
    "unit",
    "price",
    "original_price",
    "image",
    "minimum_order_quantity",
    "maximum_order_quantity",
    "track_inventory",
    "quantity",
}


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


def _make_product(retailer, category, name, **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "price": Decimal("20.00"),
        "quantity": Decimal("5.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "kg",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _make_group(retailer, category, prefix, group_name, count=2):
    return [
        _make_product(
            retailer,
            category,
            f"{prefix} {i + 1}kg",
            product_group=group_name,
            price=Decimal(f"{(i + 1) * 10}.00"),
            quantity=Decimal(f"{(i + 1) * 3}.000"),
            unit="kg",
        )
        for i in range(count)
    ]


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _variant_ids(row):
    return [item["id"] for item in row["group_variants"]]


def _assert_same_shape_as_detail(surface_row, detail_row):
    surface = surface_row["group_variants"]
    detail = detail_row["group_variants"]
    assert _variant_ids(surface_row) == _variant_ids(detail_row)
    assert len(surface) == len(detail)
    for left, right in zip(surface, detail):
        assert VARIANT_KEYS <= set(left)
        assert VARIANT_KEYS <= set(right)
        assert left == right


def _group_sibling_lookups(queries):
    """Sibling fetches. Prefetch uses product_group IN; N+1 uses =."""
    hits = []
    for query in queries:
        sql = query["sql"]
        lowered = sql.lower()
        if " where " not in lowered:
            continue
        if "to_tsvector" in lowered or "search_vector" in lowered:
            continue
        where = lowered.split(" where ", 1)[1].split(" group by ", 1)[0]
        if "product_group" not in where:
            continue
        hits.append(sql)
    return hits


@pytest.mark.django_db
class TestGroupVariantsRetailerList:
    def test_grouped_list_matches_detail_shape(self, api_client):
        owner, shop = _make_retailer("oe192_list_own", "OE192 List Shop")
        category = _make_category(shop, "OE192 List Cat")
        rice_1, rice_5 = _make_group(shop, category, "OE192 Rice", "oe192-rice")
        inactive = _make_product(
            shop,
            category,
            "OE192 Rice stale",
            product_group="oe192-rice",
            is_active=False,
        )
        unavailable = _make_product(
            shop,
            category,
            "OE192 Rice hold",
            product_group="oe192-rice",
            is_available=False,
        )

        api_client.force_authenticate(user=owner)
        detail = api_client.get(reverse("get_product_detail", args=[rice_1.id]))
        listed = api_client.get(reverse("get_retailer_products"))

        assert detail.status_code == status.HTTP_200_OK
        assert listed.status_code == status.HTTP_200_OK
        list_row = _row_by_id(listed.data, rice_1.id)
        _assert_same_shape_as_detail(list_row, detail.data)
        assert _variant_ids(list_row) == [rice_5.id]
        assert inactive.id not in _variant_ids(list_row)
        assert unavailable.id not in _variant_ids(list_row)
        sibling = list_row["group_variants"][0]
        assert sibling["name"] == rice_5.name
        assert sibling["unit"] == rice_5.unit
        assert _qty(sibling["price"]) == rice_5.price
        assert _qty(sibling["quantity"]) == rice_5.quantity

    def test_empty_group_is_empty_list(self, api_client):
        owner, shop = _make_retailer("oe192_empty_own", "OE192 Empty Shop")
        category = _make_category(shop, "OE192 Empty Cat")
        lone = _make_product(shop, category, "OE192 Lone")
        only_member = _make_product(
            shop, category, "OE192 Solo Group", product_group="oe192-solo"
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        detail_lone = api_client.get(reverse("get_product_detail", args=[lone.id]))
        detail_solo = api_client.get(
            reverse("get_product_detail", args=[only_member.id])
        )

        assert listed.status_code == status.HTTP_200_OK
        assert _row_by_id(listed.data, lone.id)["group_variants"] == []
        assert _row_by_id(listed.data, only_member.id)["group_variants"] == []
        assert detail_lone.data["group_variants"] == []
        assert detail_solo.data["group_variants"] == []

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("oe192_auth_own", "OE192 Auth Shop")
        category = _make_category(shop, "OE192 Auth Cat")
        product, _sibling = _make_group(shop, category, "OE192 Auth", "oe192-auth")
        customer = _make_customer("oe192_auth_cust")

        anon_list = api_client.get(reverse("get_retailer_products"))
        anon_search = api_client.get(reverse("search_products"))
        anon_pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert anon_list.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon_pos.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_list = api_client.get(reverse("get_retailer_products"))
        cust_search = api_client.get(reverse("search_products"))
        cust_pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert cust_list.status_code == status.HTTP_403_FORBIDDEN
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN
        assert cust_pos.status_code == status.HTTP_403_FORBIDDEN

    def test_no_cross_tenant_siblings(self, api_client):
        _owner_a, shop_a = _make_retailer("oe192_ten_a", "OE192 Tenant A")
        owner_b, shop_b = _make_retailer("oe192_ten_b", "OE192 Tenant B")
        category_a = _make_category(shop_a, "OE192 A Cat")
        category_b = _make_category(shop_b, "OE192 B Cat")
        a1, a2 = _make_group(shop_a, category_a, "OE192 A", "shared-grain")
        b1, b2 = _make_group(shop_b, category_b, "OE192 B", "shared-grain")

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[a1.id]))

        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_404_NOT_FOUND
        list_ids = {row["id"] for row in listed.data["results"]}
        assert a1.id not in list_ids
        assert a2.id not in list_ids
        b1_row = _row_by_id(listed.data, b1.id)
        assert _variant_ids(b1_row) == [b2.id]
        assert a1.id not in _variant_ids(b1_row)
        assert a2.id not in _variant_ids(b1_row)

    def test_list_avoids_per_product_sibling_lookup(self, api_client):
        owner, shop = _make_retailer("oe192_q_own", "OE192 Query Shop")
        category = _make_category(shop, "OE192 Query Cat")
        grouped = []
        for i in range(3):
            grouped.extend(
                _make_group(shop, category, f"OE192 Q{i + 1}", f"oe192-q{i + 1}")
            )

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as list_ctx:
            listed = api_client.get(reverse("get_retailer_products"))

        assert listed.status_code == status.HTTP_200_OK
        lookups = _group_sibling_lookups(list_ctx.captured_queries)
        assert len(lookups) == 1
        assert " in (" in lookups[0].lower()
        for product in grouped:
            row = _row_by_id(listed.data, product.id)
            assert len(row["group_variants"]) == 1
            assert row["group_variants"][0]["id"] != product.id


@pytest.mark.django_db
class TestGroupVariantsSearchAndPos:
    def test_search_and_pos_match_detail_shape(self, api_client):
        owner, shop = _make_retailer("oe192_pos_own", "OE192 POS Shop")
        category = _make_category(shop, "OE192 POS Cat")
        rice_1, rice_5 = _make_group(shop, category, "OE192 Atta", "oe192-atta")
        _make_product(
            shop,
            category,
            "OE192 Atta stale",
            product_group="oe192-atta",
            is_active=False,
        )

        api_client.force_authenticate(user=owner)
        detail = api_client.get(reverse("get_product_detail", args=[rice_1.id]))
        search = api_client.get(
            reverse("search_products"), {"search": "OE192 Atta 1kg"}
        )
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )

        assert detail.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        search_row = _row_by_id(search.data, rice_1.id)
        pos_row = _row_by_id(pos.data, rice_1.id)
        _assert_same_shape_as_detail(search_row, detail.data)
        _assert_same_shape_as_detail(pos_row, detail.data)
        assert rice_5.id in _variant_ids(search_row)
        assert rice_5.id in _variant_ids(pos_row)

    def test_search_and_pos_empty_group(self, api_client):
        owner, shop = _make_retailer("oe192_pos_empty", "OE192 POS Empty")
        category = _make_category(shop, "OE192 POS Empty Cat")
        lone = _make_product(shop, category, "OE192 POS Lone")

        api_client.force_authenticate(user=owner)
        search = api_client.get(
            reverse("search_products"), {"search": "OE192 POS Lone"}
        )
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert search.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert _row_by_id(search.data, lone.id)["group_variants"] == []
        assert _row_by_id(pos.data, lone.id)["group_variants"] == []

    def test_pos_and_search_stay_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe192_pos_a", "OE192 POS A")
        owner_b, shop_b = _make_retailer("oe192_pos_b", "OE192 POS B")
        category_a = _make_category(shop_a, "OE192 POS A Cat")
        category_b = _make_category(shop_b, "OE192 POS B Cat")
        a1, _a2 = _make_group(shop_a, category_a, "OE192 POSA", "shared-pos")
        b1, b2 = _make_group(shop_b, category_b, "OE192 POSB", "shared-pos")

        api_client.force_authenticate(user=owner_b)
        search = api_client.get(
            reverse("search_products"), {"search": "OE192 POSB"}
        )
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert search.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        search_ids = _variant_ids(_row_by_id(search.data, b1.id))
        pos_ids = _variant_ids(_row_by_id(pos.data, b1.id))
        assert search_ids == [b2.id]
        assert pos_ids == [b2.id]
        assert a1.id not in search_ids
        assert a1.id not in pos_ids

    def test_search_avoids_per_product_sibling_lookup(self, api_client):
        owner, shop = _make_retailer("oe192_search_q", "OE192 Search Query")
        category = _make_category(shop, "OE192 Search Query Cat")
        grouped = []
        for i in range(3):
            grouped.extend(
                _make_group(
                    shop, category, f"OE192 SQ{i + 1}", f"oe192-sq{i + 1}"
                )
            )

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as search_ctx:
            search = api_client.get(reverse("search_products"))

        assert search.status_code == status.HTTP_200_OK
        lookups = _group_sibling_lookups(search_ctx.captured_queries)
        assert len(lookups) == 1
        assert " in (" in lookups[0].lower()
        for product in grouped:
            row = _row_by_id(search.data, product.id)
            assert len(row["group_variants"]) == 1

    def test_pos_avoids_per_product_sibling_lookup(self, api_client):
        owner, shop = _make_retailer("oe192_pos_q", "OE192 POS Query")
        category = _make_category(shop, "OE192 POS Query Cat")
        grouped = []
        for i in range(3):
            grouped.extend(
                _make_group(shop, category, f"OE192 PQ{i + 1}", f"oe192-pq{i + 1}")
            )

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as pos_ctx:
            pos = api_client.get(
                reverse("get_retailer_products"), {"no_page": "true"}
            )

        assert pos.status_code == status.HTTP_200_OK
        lookups = _group_sibling_lookups(pos_ctx.captured_queries)
        assert len(lookups) == 1
        assert " in (" in lookups[0].lower()
        for product in grouped:
            row = _row_by_id(pos.data, product.id)
            assert len(row["group_variants"]) == 1
