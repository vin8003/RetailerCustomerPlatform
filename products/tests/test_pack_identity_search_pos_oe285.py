"""
OE-285 / F-0019 follow-on — pack identity scalars on search + POS no_page.

Same values/shape as list/detail (OE-191). Non-pack keeps defaults/nulls.
Shop-scoped. No N+1. READ only — no pack write.
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

PACK_IDENTITY_KEYS = ("is_parent_bulk", "parent_bulk_product", "conversion_factor")


def _qty(val):
    if val is None:
        return None
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


def _make_simple_product(retailer, category, name, quantity, **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "price": Decimal("20.00"),
        "quantity": quantity,
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "piece",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _make_pack(retailer, category, prefix, parent_qty=Decimal("10.000")):
    parent = _make_simple_product(
        retailer,
        category,
        f"{prefix} Case",
        parent_qty,
        is_parent_bulk=True,
        unit="case",
        price=Decimal("100.00"),
    )
    child = _make_simple_product(
        retailer,
        category,
        f"{prefix} Piece",
        Decimal("0"),
        parent_bulk_product=parent,
        conversion_factor=Decimal("0.1000"),
        price=Decimal("12.00"),
    )
    parent.refresh_from_db()
    child.refresh_from_db()
    return parent, child


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _assert_pack_identity_matches_detail(surface_row, detail_row):
    for key in PACK_IDENTITY_KEYS:
        assert key in surface_row
        assert key in detail_row
        left, right = surface_row[key], detail_row[key]
        if key == "conversion_factor":
            assert _qty(left) == _qty(right)
        else:
            assert left == right


def _parent_row_lookups(queries):
    """Singular product PK fetches (N+1 parent object). Prefetch uses IN."""
    hits = []
    for query in queries:
        sql = query["sql"]
        lowered = sql.lower()
        if 'from "product"' not in lowered and "from product" not in lowered:
            continue
        if " where " not in lowered:
            continue
        where = lowered.split(" where ", 1)[1].split(" group by ", 1)[0]
        if "parent_bulk_product_id" in where:
            continue
        if " in (" in where:
            continue
        if '"product"."id" =' in where or "product.id =" in where:
            hits.append(sql)
    return hits


@pytest.mark.django_db
class TestPackIdentitySearchAndPos:
    def test_search_and_pos_match_detail_shape(self, api_client):
        owner, shop = _make_retailer("oe285_pos_own", "OE285 POS Shop")
        category = _make_category(shop, "OE285 POS Cat")
        parent, child = _make_pack(shop, category, "OE285")

        api_client.force_authenticate(user=owner)
        parent_detail = api_client.get(
            reverse("get_product_detail", args=[parent.id])
        )
        child_detail = api_client.get(
            reverse("get_product_detail", args=[child.id])
        )
        search = api_client.get(
            reverse("search_products"), {"search": "OE285"}
        )
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )

        assert parent_detail.status_code == status.HTTP_200_OK
        assert child_detail.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK

        search_parent = _row_by_id(search.data, parent.id)
        search_child = _row_by_id(search.data, child.id)
        pos_parent = _row_by_id(pos.data, parent.id)
        pos_child = _row_by_id(pos.data, child.id)

        _assert_pack_identity_matches_detail(search_parent, parent_detail.data)
        _assert_pack_identity_matches_detail(search_child, child_detail.data)
        _assert_pack_identity_matches_detail(pos_parent, parent_detail.data)
        _assert_pack_identity_matches_detail(pos_child, child_detail.data)

        for row in (search_parent, pos_parent):
            assert row["is_parent_bulk"] is True
            assert row["parent_bulk_product"] is None
            assert row["conversion_factor"] is None
        for row in (search_child, pos_child):
            assert row["is_parent_bulk"] is False
            assert row["parent_bulk_product"] == parent.id
            assert _qty(row["conversion_factor"]) == Decimal("0.1000")

    def test_search_and_pos_non_pack_defaults(self, api_client):
        owner, shop = _make_retailer("oe285_empty_own", "OE285 Empty Shop")
        category = _make_category(shop, "OE285 Empty Cat")
        standalone = _make_simple_product(
            shop, category, "OE285 Standalone", Decimal("4.000")
        )

        api_client.force_authenticate(user=owner)
        detail = api_client.get(
            reverse("get_product_detail", args=[standalone.id])
        )
        search = api_client.get(
            reverse("search_products"), {"search": "OE285 Standalone"}
        )
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )

        assert detail.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        search_row = _row_by_id(search.data, standalone.id)
        pos_row = _row_by_id(pos.data, standalone.id)
        _assert_pack_identity_matches_detail(search_row, detail.data)
        _assert_pack_identity_matches_detail(pos_row, detail.data)
        for row in (search_row, pos_row, detail.data):
            assert row["is_parent_bulk"] is False
            assert row["parent_bulk_product"] is None
            assert row["conversion_factor"] is None

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe285_auth_own", "OE285 Auth Shop")
        category = _make_category(shop, "OE285 Auth Cat")
        _parent, _child = _make_pack(shop, category, "OE285 Auth")
        customer = _make_customer("oe285_auth_cust")

        anon_search = api_client.get(reverse("search_products"))
        anon_pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon_pos.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_search = api_client.get(reverse("search_products"))
        cust_pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN
        assert cust_pos.status_code == status.HTTP_403_FORBIDDEN

    def test_search_and_pos_stay_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe285_ten_a", "OE285 Tenant A")
        owner_b, shop_b = _make_retailer("oe285_ten_b", "OE285 Tenant B")
        category_a = _make_category(shop_a, "OE285 A Cat")
        category_b = _make_category(shop_b, "OE285 B Cat")
        parent_a, child_a = _make_pack(shop_a, category_a, "OE285 A")
        parent_b, child_b = _make_pack(shop_b, category_b, "OE285 B")

        api_client.force_authenticate(user=owner_b)
        search = api_client.get(reverse("search_products"))
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        detail_a = api_client.get(reverse("get_product_detail", args=[parent_a.id]))

        assert search.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        search_ids = {row["id"] for row in search.data["results"]}
        pos_ids = {row["id"] for row in pos.data}
        assert parent_a.id not in search_ids
        assert parent_a.id not in pos_ids
        assert child_a.id not in search_ids
        assert child_a.id not in pos_ids
        assert parent_b.id in search_ids
        assert parent_b.id in pos_ids
        assert child_b.id in search_ids
        assert child_b.id in pos_ids
        search_child = _row_by_id(search.data, child_b.id)
        pos_child = _row_by_id(pos.data, child_b.id)
        assert search_child["parent_bulk_product"] == parent_b.id
        assert pos_child["parent_bulk_product"] == parent_b.id
        assert search_child["parent_bulk_product"] != parent_a.id
        assert pos_child["parent_bulk_product"] != parent_a.id

    def test_search_avoids_per_child_parent_lookup(self, api_client):
        owner, shop = _make_retailer("oe285_search_q", "OE285 Search Query")
        category = _make_category(shop, "OE285 Search Query Cat")
        children = []
        for i in range(3):
            _parent, child = _make_pack(shop, category, f"OE285 SQ{i + 1}")
            children.append(child)

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as search_ctx:
            search = api_client.get(reverse("search_products"))

        assert search.status_code == status.HTTP_200_OK
        assert _parent_row_lookups(search_ctx.captured_queries) == []
        for child in children:
            row = _row_by_id(search.data, child.id)
            assert row["parent_bulk_product"] == child.parent_bulk_product_id
            assert _qty(row["conversion_factor"]) == Decimal("0.1000")

    def test_pos_avoids_per_child_parent_lookup(self, api_client):
        owner, shop = _make_retailer("oe285_pos_q", "OE285 POS Query")
        category = _make_category(shop, "OE285 POS Query Cat")
        children = []
        for i in range(3):
            _parent, child = _make_pack(shop, category, f"OE285 PQ{i + 1}")
            children.append(child)

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as pos_ctx:
            pos = api_client.get(
                reverse("get_retailer_products"), {"no_page": "true"}
            )

        assert pos.status_code == status.HTTP_200_OK
        assert _parent_row_lookups(pos_ctx.captured_queries) == []
        for child in children:
            row = _row_by_id(pos.data, child.id)
            assert row["parent_bulk_product"] == child.parent_bulk_product_id
            assert _qty(row["conversion_factor"]) == Decimal("0.1000")
