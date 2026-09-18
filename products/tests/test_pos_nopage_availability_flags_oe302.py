"""
OE-302 / F follow-on — is_featured / is_available / is_in_stock on POS no_page.

Same values as list/detail. False stays false (do not omit).
Search serializer Meta is not edited this ticket. Auth/tenancy
unchanged. READ only.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory
from products.serializers import ProductSearchSerializer
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

POS_BOOLS = ("is_featured", "is_available", "is_in_stock")


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
        "purchase_price": Decimal("10.00"),
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "is_featured": False,
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


def _assert_bools_match(pos_row, list_row, detail, expected):
    for key, value in expected.items():
        assert key in pos_row
        assert pos_row[key] is value
        assert pos_row[key] == list_row[key]
        assert pos_row[key] == detail[key]


@pytest.mark.django_db
class TestPosNoPageAvailabilityFlags:
    def test_pos_bools_match_list_and_detail(self, api_client):
        owner, shop = _make_retailer("oe302_hit_own", "OE302 Flag Shop")
        category = _make_category(shop, "OE302 Flag Cat")
        featured = _make_product(
            shop,
            category,
            "OE302 Featured Atta",
            is_featured=True,
            is_available=True,
            quantity=Decimal("8.000"),
            track_inventory=True,
        )
        staple = _make_product(
            shop,
            category,
            "OE302 Staple Rice",
            is_featured=False,
            is_available=True,
            quantity=Decimal("3.000"),
            track_inventory=True,
        )
        hidden = _make_product(
            shop,
            category,
            "OE302 Hidden Oil",
            is_featured=False,
            is_available=False,
            quantity=Decimal("5.000"),
            track_inventory=True,
        )
        empty = _make_product(
            shop,
            category,
            "OE302 Empty Sugar",
            is_featured=True,
            is_available=True,
            quantity=Decimal("0.000"),
            track_inventory=True,
        )

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        featured_detail = _detail(api_client, featured.id)
        staple_detail = _detail(api_client, staple.id)
        hidden_detail = _detail(api_client, hidden.id)
        empty_detail = _detail(api_client, empty.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert featured_detail.status_code == status.HTTP_200_OK
        assert staple_detail.status_code == status.HTTP_200_OK
        assert hidden_detail.status_code == status.HTTP_200_OK
        assert empty_detail.status_code == status.HTTP_200_OK

        cases = (
            (
                featured,
                featured_detail.data,
                {
                    "is_featured": True,
                    "is_available": True,
                    "is_in_stock": True,
                },
            ),
            (
                staple,
                staple_detail.data,
                {
                    "is_featured": False,
                    "is_available": True,
                    "is_in_stock": True,
                },
            ),
            (
                hidden,
                hidden_detail.data,
                {
                    "is_featured": False,
                    "is_available": False,
                    "is_in_stock": True,
                },
            ),
            (
                empty,
                empty_detail.data,
                {
                    "is_featured": True,
                    "is_available": True,
                    "is_in_stock": False,
                },
            ),
        )
        for product, detail, expected in cases:
            list_row = _row_by_id(listed.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            _assert_bools_match(pos_row, list_row, detail, expected)
            assert pos_row["is_active"] is True

    def test_false_bools_stay_false(self, api_client):
        owner, shop = _make_retailer("oe302_false_own", "OE302 False Shop")
        category = _make_category(shop, "OE302 False Cat")
        product = _make_product(
            shop,
            category,
            "OE302 False Staple",
            is_featured=False,
            is_available=False,
            quantity=Decimal("0.000"),
            track_inventory=True,
        )
        assert product.is_featured is False
        assert product.is_available is False
        assert product.is_in_stock is False

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        detail = _detail(api_client, product.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        pos_row = _row_by_id(pos.data, product.id)
        list_row = _row_by_id(listed.data, product.id)
        for key in POS_BOOLS:
            assert key in pos_row
            assert pos_row[key] is False
            assert pos_row[key] == list_row[key]
            assert pos_row[key] == detail.data[key]
            assert pos_row.get(key) is False

    def test_untracked_is_in_stock_mirrors_is_available(self, api_client):
        owner, shop = _make_retailer("oe302_untrk_own", "OE302 Untracked Shop")
        category = _make_category(shop, "OE302 Untracked Cat")
        available = _make_product(
            shop,
            category,
            "OE302 Untracked Open",
            track_inventory=False,
            is_available=True,
            quantity=Decimal("0.000"),
        )
        closed = _make_product(
            shop,
            category,
            "OE302 Untracked Closed",
            track_inventory=False,
            is_available=False,
            quantity=Decimal("0.000"),
        )
        assert available.is_in_stock is True
        assert closed.is_in_stock is False

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        available_detail = _detail(api_client, available.id)
        closed_detail = _detail(api_client, closed.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert available_detail.status_code == status.HTTP_200_OK
        assert closed_detail.status_code == status.HTTP_200_OK

        _assert_bools_match(
            _row_by_id(pos.data, available.id),
            _row_by_id(listed.data, available.id),
            available_detail.data,
            {
                "is_featured": False,
                "is_available": True,
                "is_in_stock": True,
            },
        )
        _assert_bools_match(
            _row_by_id(pos.data, closed.id),
            _row_by_id(listed.data, closed.id),
            closed_detail.data,
            {
                "is_featured": False,
                "is_available": False,
                "is_in_stock": False,
            },
        )

    def test_search_serializer_meta_untouched(self):
        fields = ProductSearchSerializer.Meta.fields
        assert "is_featured" in fields
        assert "is_active" in fields
        assert "is_available" not in fields
        assert "is_in_stock" not in fields

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe302_auth_own", "OE302 Auth Shop")
        category = _make_category(shop, "OE302 Auth Cat")
        _make_product(
            shop,
            category,
            "OE302 Auth Rice",
            is_featured=True,
            is_available=True,
        )
        customer = _make_customer("oe302_auth_cust")

        anon = _pos(api_client)
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust = _pos(api_client)
        assert cust.status_code == status.HTTP_403_FORBIDDEN

    def test_pos_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe302_ten_a", "OE302 Tenant A")
        owner_b, shop_b = _make_retailer("oe302_ten_b", "OE302 Tenant B")
        cat_a = _make_category(shop_a, "OE302 A Cat")
        cat_b = _make_category(shop_b, "OE302 B Cat")
        product_a = _make_product(
            shop_a,
            cat_a,
            "OE302 A SKU",
            is_featured=True,
            is_available=True,
        )
        product_b = _make_product(
            shop_b,
            cat_b,
            "OE302 B SKU",
            is_featured=False,
            is_available=False,
            quantity=Decimal("0.000"),
        )

        api_client.force_authenticate(user=owner_b)
        pos = _pos(api_client)
        detail_a = _detail(api_client, product_a.id)
        detail_b = _detail(api_client, product_b.id)

        assert pos.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        assert detail_b.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in pos.data}
        assert product_a.id not in ids
        assert product_b.id in ids
        pos_row = _row_by_id(pos.data, product_b.id)
        assert pos_row["is_featured"] is False
        assert pos_row["is_available"] is False
        assert pos_row["is_in_stock"] is False
        assert pos_row["is_featured"] == detail_b.data["is_featured"]
        assert pos_row["is_available"] == detail_b.data["is_available"]
        assert pos_row["is_in_stock"] == detail_b.data["is_in_stock"]
