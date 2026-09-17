"""
OE-283 / F-0019 follow-on — fractional_children on search + POS no_page.

Same child shape as list/detail (OE-191). Non-parent → []. Shop-scoped.
No N+1. No BOM / assemble write.
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

CHILD_KEYS = {"id", "name", "conversion_factor", "saleable_quantity"}


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


def _child_ids(row):
    return [item["id"] for item in row["fractional_children"]]


def _assert_same_shape_as_detail(surface_row, detail_row):
    surface = surface_row["fractional_children"]
    detail = detail_row["fractional_children"]
    assert _child_ids(surface_row) == _child_ids(detail_row)
    assert len(surface) == len(detail)
    for left, right in zip(surface, detail):
        assert set(left) == CHILD_KEYS
        assert set(right) == CHILD_KEYS
        assert left == right


def _child_lookups(queries):
    """fractional_children fetches. Prefetch uses IN; N+1 uses =."""
    hits = []
    for query in queries:
        sql = query["sql"]
        lowered = sql.lower()
        if "parent_bulk_product_id" not in lowered or " where " not in lowered:
            continue
        where = lowered.split(" where ", 1)[1].split(" group by ", 1)[0]
        if "parent_bulk_product_id" not in where:
            continue
        hits.append(sql)
    return hits


@pytest.mark.django_db
class TestFractionalChildrenSearchAndPos:
    def test_search_and_pos_match_detail_shape(self, api_client):
        owner, shop = _make_retailer("oe283_pos_own", "OE283 POS Shop")
        category = _make_category(shop, "OE283 POS Cat")
        parent, child = _make_pack(shop, category, "OE283")
        inactive = _make_simple_product(
            shop,
            category,
            "OE283 Inactive Piece",
            Decimal("0"),
            parent_bulk_product=parent,
            conversion_factor=Decimal("0.2000"),
            is_active=False,
        )
        parent.refresh_from_db()
        child.refresh_from_db()
        assert parent.saleable_quantity() == Decimal("10.000")
        assert child.saleable_quantity() == Decimal("100")

        api_client.force_authenticate(user=owner)
        detail = api_client.get(reverse("get_product_detail", args=[parent.id]))
        search = api_client.get(
            reverse("search_products"), {"search": "OE283 Case"}
        )
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )

        assert detail.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        search_row = _row_by_id(search.data, parent.id)
        pos_row = _row_by_id(pos.data, parent.id)
        _assert_same_shape_as_detail(search_row, detail.data)
        _assert_same_shape_as_detail(pos_row, detail.data)
        for row in (search_row, pos_row):
            children = row["fractional_children"]
            assert [c["id"] for c in children] == [child.id]
            assert children[0]["name"] == child.name
            assert _qty(children[0]["conversion_factor"]) == Decimal("0.1000")
            assert _qty(children[0]["saleable_quantity"]) == Decimal("100")
            assert inactive.id not in _child_ids(row)

    def test_search_and_pos_non_parent_empty(self, api_client):
        owner, shop = _make_retailer("oe283_empty_own", "OE283 Empty Shop")
        category = _make_category(shop, "OE283 Empty Cat")
        standalone = _make_simple_product(
            shop, category, "OE283 Standalone", Decimal("4.000")
        )
        _parent, child = _make_pack(shop, category, "OE283 Empty")

        api_client.force_authenticate(user=owner)
        search = api_client.get(
            reverse("search_products"), {"search": "OE283"}
        )
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert search.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert _row_by_id(search.data, standalone.id)["fractional_children"] == []
        assert _row_by_id(search.data, child.id)["fractional_children"] == []
        assert _row_by_id(pos.data, standalone.id)["fractional_children"] == []
        assert _row_by_id(pos.data, child.id)["fractional_children"] == []

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe283_auth_own", "OE283 Auth Shop")
        category = _make_category(shop, "OE283 Auth Cat")
        _parent, _child = _make_pack(shop, category, "OE283 Auth")
        customer = _make_customer("oe283_auth_cust")

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
        _owner_a, shop_a = _make_retailer("oe283_ten_a", "OE283 Tenant A")
        owner_b, shop_b = _make_retailer("oe283_ten_b", "OE283 Tenant B")
        category_a = _make_category(shop_a, "OE283 A Cat")
        category_b = _make_category(shop_b, "OE283 B Cat")
        parent_a, child_a = _make_pack(shop_a, category_a, "OE283 A")
        parent_b, child_b = _make_pack(shop_b, category_b, "OE283 B")

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
        assert _child_ids(_row_by_id(search.data, parent_b.id)) == [child_b.id]
        assert _child_ids(_row_by_id(pos.data, parent_b.id)) == [child_b.id]
        assert child_a.id not in _child_ids(_row_by_id(search.data, parent_b.id))
        assert child_a.id not in _child_ids(_row_by_id(pos.data, parent_b.id))

    def test_public_search_omits_fractional_children(self, api_client):
        _owner, shop = _make_retailer("oe283_pub_own", "OE283 Public Shop")
        category = _make_category(shop, "OE283 Public Cat")
        parent, _child = _make_pack(shop, category, "OE283 Public")

        public = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "OE283 Public Case"},
        )
        assert public.status_code == status.HTTP_200_OK
        row = _row_by_id(public.data, parent.id)
        assert "fractional_children" not in row

    def test_search_avoids_per_parent_child_lookup(self, api_client):
        owner, shop = _make_retailer("oe283_search_q", "OE283 Search Query")
        category = _make_category(shop, "OE283 Search Query Cat")
        parents = []
        for i in range(3):
            parent, _child = _make_pack(shop, category, f"OE283 SQ{i + 1}")
            parents.append(parent)

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as search_ctx:
            search = api_client.get(reverse("search_products"))

        assert search.status_code == status.HTTP_200_OK
        lookups = _child_lookups(search_ctx.captured_queries)
        assert len(lookups) == 1
        assert " in (" in lookups[0].lower()
        for parent in parents:
            children = _row_by_id(search.data, parent.id)["fractional_children"]
            assert len(children) == 1
            assert _qty(children[0]["saleable_quantity"]) == Decimal("100")

    def test_pos_avoids_per_parent_child_lookup(self, api_client):
        owner, shop = _make_retailer("oe283_pos_q", "OE283 POS Query")
        category = _make_category(shop, "OE283 POS Query Cat")
        parents = []
        for i in range(3):
            parent, _child = _make_pack(shop, category, f"OE283 PQ{i + 1}")
            parents.append(parent)

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as pos_ctx:
            pos = api_client.get(
                reverse("get_retailer_products"), {"no_page": "true"}
            )

        assert pos.status_code == status.HTTP_200_OK
        lookups = _child_lookups(pos_ctx.captured_queries)
        assert len(lookups) == 1
        assert " in (" in lookups[0].lower()
        for parent in parents:
            children = _row_by_id(pos.data, parent.id)["fractional_children"]
            assert len(children) == 1
            assert _qty(children[0]["saleable_quantity"]) == Decimal("100")
