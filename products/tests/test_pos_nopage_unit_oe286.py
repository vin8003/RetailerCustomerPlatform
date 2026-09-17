"""
OE-286 / F follow-on — top-level unit on POS no_page.

Same value as list/detail Product.unit. Empty/null stays empty/null
(no invented 'piece' on read). Auth/tenancy unchanged. READ only.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory
from retailers.models import OrgRole, OrgStaffMembership, RetailerProfile
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


def _make_staff(org, username, permissions):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    role = OrgRole.objects.create(
        organization=org,
        slug=f"role_{username}",
        name=f"Role {username}",
        permissions=list(permissions),
        is_system=False,
    )
    OrgStaffMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        is_active=True,
    )
    return user


def _make_location_profile(user, org, shop_name):
    return RetailerProfile.objects.create(
        user=user,
        organization=org,
        shop_name=shop_name,
        address_line1="2 Side",
        city="City",
        state="State",
        pincode="110002",
        is_active=True,
    )


def _make_category(retailer, name):
    return ProductCategory.objects.create(name=name, retailer=retailer)


def _make_product(retailer, category, name, unit="piece", **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
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


@pytest.mark.django_db
class TestPosNoPageUnit:
    def test_pos_unit_matches_list_and_detail(self, api_client):
        owner, shop = _make_retailer("oe286_hit_own", "OE286 Unit Shop")
        category = _make_category(shop, "OE286 Unit Cat")
        kg = _make_product(shop, category, "OE286 Atta", unit="kg")
        pack = _make_product(shop, category, "OE286 Biscuits", unit="pack")
        default = _make_product(shop, category, "OE286 Piece Default", unit="piece")

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = api_client.get(reverse("search_products"), {"search": "OE286"})
        kg_detail = _detail(api_client, kg.id)
        pack_detail = _detail(api_client, pack.id)
        default_detail = _detail(api_client, default.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert kg_detail.status_code == status.HTTP_200_OK
        assert pack_detail.status_code == status.HTTP_200_OK
        assert default_detail.status_code == status.HTTP_200_OK

        for product, expected, detail in (
            (kg, "kg", kg_detail.data),
            (pack, "pack", pack_detail.data),
            (default, "piece", default_detail.data),
        ):
            list_row = _row_by_id(listed.data, product.id)
            search_row = _row_by_id(search.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            assert "unit" in pos_row
            assert pos_row["unit"] == expected
            assert pos_row["unit"] == list_row["unit"]
            assert pos_row["unit"] == search_row["unit"]
            assert pos_row["unit"] == detail["unit"]

    def test_empty_unit_stays_empty_like_list(self, api_client):
        owner, shop = _make_retailer("oe286_empty_own", "OE286 Empty Shop")
        category = _make_category(shop, "OE286 Empty Cat")
        product = _make_product(shop, category, "OE286 Blank Unit", unit="kg")
        Product.objects.filter(pk=product.id).update(unit="")
        product.refresh_from_db()
        assert product.unit == ""

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        detail = _detail(api_client, product.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        pos_row = _row_by_id(pos.data, product.id)
        list_row = _row_by_id(listed.data, product.id)
        assert pos_row["unit"] == list_row["unit"]
        assert pos_row["unit"] == detail.data["unit"]
        assert pos_row["unit"] == ""
        assert pos_row["unit"] != "piece"

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe286_auth_own", "OE286 Auth Shop")
        category = _make_category(shop, "OE286 Auth Cat")
        _make_product(shop, category, "OE286 Auth Rice", unit="kg")
        customer = _make_customer("oe286_auth_cust")

        anon = _pos(api_client)
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust = _pos(api_client)
        assert cust.status_code == status.HTTP_403_FORBIDDEN

    def test_pos_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe286_ten_a", "OE286 Tenant A")
        owner_b, shop_b = _make_retailer("oe286_ten_b", "OE286 Tenant B")
        cat_a = _make_category(shop_a, "OE286 A Cat")
        cat_b = _make_category(shop_b, "OE286 B Cat")
        product_a = _make_product(shop_a, cat_a, "OE286 A SKU", unit="liter")
        product_b = _make_product(shop_b, cat_b, "OE286 B SKU", unit="dozen")

        api_client.force_authenticate(user=owner_b)
        pos = _pos(api_client)
        detail_a = _detail(api_client, product_a.id)

        assert pos.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        ids = {row["id"] for row in pos.data}
        assert product_a.id not in ids
        assert product_b.id in ids
        assert _row_by_id(pos.data, product_b.id)["unit"] == "dozen"

    def test_public_catalog_unchanged(self, api_client):
        _owner, shop = _make_retailer("oe286_pub_own", "OE286 Public Shop")
        category = _make_category(shop, "OE286 Public Cat")
        product = _make_product(shop, category, "OE286 Public Milk", unit="liter")

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        assert public.status_code == status.HTTP_200_OK
        row = _row_by_id(public.data, product.id)
        assert row["unit"] == "liter"
        assert "saleable_quantity" not in row
        assert "margin_percent" not in row

    def test_pos_keeps_oe285_pack_identity(self, api_client):
        owner, shop = _make_retailer("oe286_pack_own", "OE286 Pack Shop")
        category = _make_category(shop, "OE286 Pack Cat")
        parent = _make_product(
            shop,
            category,
            "OE286 Case",
            unit="box",
            is_parent_bulk=True,
            price=Decimal("100.00"),
            purchase_price=Decimal("60.00"),
        )
        child = _make_product(
            shop,
            category,
            "OE286 Piece",
            unit="piece",
            parent_bulk_product=parent,
            conversion_factor=Decimal("0.1000"),
            price=Decimal("12.00"),
            purchase_price=Decimal("6.00"),
        )

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        parent_detail = _detail(api_client, parent.id)
        child_detail = _detail(api_client, child.id)

        assert pos.status_code == status.HTTP_200_OK
        assert parent_detail.status_code == status.HTTP_200_OK
        assert child_detail.status_code == status.HTTP_200_OK

        pos_parent = _row_by_id(pos.data, parent.id)
        pos_child = _row_by_id(pos.data, child.id)
        assert pos_parent["unit"] == parent_detail.data["unit"] == "box"
        assert pos_child["unit"] == child_detail.data["unit"] == "piece"
        assert pos_parent["is_parent_bulk"] is True
        assert pos_parent["parent_bulk_product"] is None
        assert pos_parent["conversion_factor"] is None
        assert pos_child["is_parent_bulk"] is False
        assert pos_child["parent_bulk_product"] == parent.id
        assert Decimal(str(pos_child["conversion_factor"])) == Decimal("0.1000")

    def test_cashier_sees_unit_omits_margin(self, api_client):
        owner, shop = _make_retailer("oe286_cash_own", "OE286 Cash Shop")
        cashier = _make_staff(shop.organization, "oe286_cashier", [])
        loc = _make_location_profile(cashier, shop.organization, "OE286 Cash Loc")
        category = _make_category(loc, "OE286 Cash Cat")
        product = _make_product(
            loc,
            category,
            "OE286 Cash Sugar",
            unit="kg",
            purchase_price=Decimal("7.00"),
        )

        api_client.force_authenticate(user=cashier)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK
        row = _row_by_id(pos.data, product.id)
        assert row["unit"] == "kg"
        assert "margin_percent" not in row

    def test_pos_keeps_oe284_margin_percent(self, api_client):
        owner, shop = _make_retailer("oe286_margin_own", "OE286 Margin Shop")
        category = _make_category(shop, "OE286 Margin Cat")
        product = _make_product(
            shop,
            category,
            "OE286 Margin Atta",
            unit="kg",
            price=Decimal("20.00"),
            purchase_price=Decimal("10.00"),
        )

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK
        row = _row_by_id(pos.data, product.id)
        assert row["unit"] == "kg"
        assert row["margin_percent"] == "50.00"
