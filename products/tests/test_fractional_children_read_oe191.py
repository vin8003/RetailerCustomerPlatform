"""
OE-191 / F-0019 — active fractional_children on retailer parent SKU reads.

Thin EXTEND only. Non-parent → []. Cross-tenant detail → 404.
No BOM / assemble write. Search and POS no_page stay unchanged.
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


def _child_lookups(queries):
    """Per-parent fractional_children hits (prefetch uses IN, not =)."""
    hits = []
    for query in queries:
        sql = query["sql"]
        lowered = sql.lower()
        if "parent_bulk_product_id" not in lowered:
            continue
        if " where " not in lowered:
            continue
        where = lowered.split(" where ", 1)[1]
        if "parent_bulk_product_id" not in where:
            continue
        hits.append(sql)
    return hits


@pytest.mark.django_db
class TestFractionalChildrenRetailerReads:
    def test_parent_detail_and_list_include_active_children(self, api_client):
        owner, shop = _make_retailer("oe191_parent_own", "OE191 Parent Shop")
        category = _make_category(shop, "OE191 Parent Cat")
        parent, child = _make_pack(shop, category, "OE191")
        inactive = _make_simple_product(
            shop,
            category,
            "OE191 Inactive Piece",
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
        listed = api_client.get(reverse("get_retailer_products"))

        assert detail.status_code == status.HTTP_200_OK
        assert listed.status_code == status.HTTP_200_OK

        list_row = _row_by_id(listed.data, parent.id)
        for row in (detail.data, list_row):
            children = row["fractional_children"]
            assert [c["id"] for c in children] == [child.id]
            assert children[0]["name"] == child.name
            assert _qty(children[0]["conversion_factor"]) == Decimal("0.1000")
            assert _qty(children[0]["saleable_quantity"]) == Decimal("100")
            assert inactive.id not in [c["id"] for c in children]

    def test_non_parent_and_child_sku_return_empty(self, api_client):
        owner, shop = _make_retailer("oe191_empty_own", "OE191 Empty Shop")
        category = _make_category(shop, "OE191 Empty Cat")
        standalone = _make_simple_product(
            shop, category, "OE191 Standalone", Decimal("4.000")
        )
        parent, child = _make_pack(shop, category, "OE191 Empty")

        api_client.force_authenticate(user=owner)
        standalone_detail = api_client.get(
            reverse("get_product_detail", args=[standalone.id])
        )
        child_detail = api_client.get(reverse("get_product_detail", args=[child.id]))
        listed = api_client.get(reverse("get_retailer_products"))

        assert standalone_detail.status_code == status.HTTP_200_OK
        assert child_detail.status_code == status.HTTP_200_OK
        assert standalone_detail.data["fractional_children"] == []
        assert child_detail.data["fractional_children"] == []
        assert _row_by_id(listed.data, standalone.id)["fractional_children"] == []
        assert _row_by_id(listed.data, child.id)["fractional_children"] == []
        assert _row_by_id(listed.data, parent.id)["fractional_children"]

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("oe191_auth_own", "OE191 Auth Shop")
        category = _make_category(shop, "OE191 Auth Cat")
        parent, _child = _make_pack(shop, category, "OE191 Auth")
        customer = _make_customer("oe191_auth_cust")

        anon_list = api_client.get(reverse("get_retailer_products"))
        anon_detail = api_client.get(
            reverse("get_product_detail", args=[parent.id])
        )
        assert anon_list.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon_detail.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_list = api_client.get(reverse("get_retailer_products"))
        cust_detail = api_client.get(
            reverse("get_product_detail", args=[parent.id])
        )
        assert cust_list.status_code == status.HTTP_403_FORBIDDEN
        assert cust_detail.status_code == status.HTTP_403_FORBIDDEN

    def test_no_cross_tenant_read(self, api_client):
        _owner_a, shop_a = _make_retailer("oe191_ten_a", "OE191 Tenant A")
        owner_b, shop_b = _make_retailer("oe191_ten_b", "OE191 Tenant B")
        category_a = _make_category(shop_a, "OE191 A Cat")
        category_b = _make_category(shop_b, "OE191 B Cat")
        parent_a, _child_a = _make_pack(shop_a, category_a, "OE191 A")
        parent_b, _child_b = _make_pack(shop_b, category_b, "OE191 B")

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[parent_a.id]))

        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_404_NOT_FOUND
        assert detail.data.get("id") != parent_a.id
        list_ids = {row["id"] for row in listed.data["results"]}
        assert parent_a.id not in list_ids
        assert parent_b.id in list_ids
        assert _row_by_id(listed.data, parent_b.id)["fractional_children"]

    def test_public_catalog_omits_fractional_children(self, api_client):
        _owner, shop = _make_retailer("oe191_pub_own", "OE191 Public Shop")
        category = _make_category(shop, "OE191 Public Cat")
        parent, _child = _make_pack(shop, category, "OE191 Public")

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        assert public.status_code == status.HTTP_200_OK
        row = _row_by_id(public.data, parent.id)
        assert "fractional_children" not in row

    def test_search_and_pos_omit_fractional_children(self, api_client):
        owner, shop = _make_retailer("oe191_pos_own", "OE191 POS Shop")
        category = _make_category(shop, "OE191 POS Cat")
        parent, _child = _make_pack(shop, category, "OE191 POS")

        api_client.force_authenticate(user=owner)
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        search = api_client.get(
            reverse("search_products"), {"search": "OE191 POS Case"}
        )
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert "fractional_children" not in _row_by_id(pos.data, parent.id)
        assert "fractional_children" not in _row_by_id(search.data, parent.id)

    def test_list_avoids_per_parent_child_lookup(self, api_client):
        owner, shop = _make_retailer("oe191_q_own", "OE191 Query Shop")
        category = _make_category(shop, "OE191 Query Cat")
        parents = []
        for i in range(3):
            parent, _child = _make_pack(shop, category, f"OE191 Q{i + 1}")
            parents.append(parent)

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as list_ctx:
            listed = api_client.get(reverse("get_retailer_products"))

        assert listed.status_code == status.HTTP_200_OK
        lookups = _child_lookups(list_ctx.captured_queries)
        assert len(lookups) == 1
        assert " in (" in lookups[0].lower()
        for parent in parents:
            children = _row_by_id(listed.data, parent.id)["fractional_children"]
            assert len(children) == 1
            assert _qty(children[0]["saleable_quantity"]) == Decimal("100")
