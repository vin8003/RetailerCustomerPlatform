"""
Optional color on Product list serializer.

Echo Product.color only when the attribute exists. Missing field or
null stays null (no invented color). Auth/tenancy unchanged. READ only.
Does not touch ProductSearchSerializer Meta, POS no_page, or detail.
Dummy / local only.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory
from products.serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    product_color,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8903541111111"
PRIMARY_B = "8903542222222"


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
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "piece",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _rows(payload):
    return payload if isinstance(payload, list) else payload.get("results") or []


def _list_row(payload, product_id):
    for row in _rows(payload):
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from list payload")


def _list_url():
    return reverse("get_retailer_products")


def _pos(api_client):
    return api_client.get(_list_url(), {"no_page": "true"})


def _product_table_reads(captured):
    return [
        q["sql"]
        for q in captured.captured_queries
        if 'FROM "product"' in q["sql"]
    ]


@pytest.mark.django_db
class TestProductColorHelper:
    def test_missing_attribute_is_null(self):
        assert not hasattr(Product, "color")
        assert product_color(SimpleNamespace(name="no-color")) is None

    def test_none_product_is_null(self):
        assert product_color(None) is None

    def test_present_value_is_echoed(self):
        assert product_color(SimpleNamespace(color="red")) == "red"

    def test_null_and_empty_passthrough(self):
        assert product_color(SimpleNamespace(color=None)) is None
        assert product_color(SimpleNamespace(color="")) == ""


@pytest.mark.django_db
class TestProductListColor:
    def test_list_color_null_when_product_has_no_field(self, api_client):
        owner, shop = _make_retailer("list_color_miss_own", "List Color Missing Shop")
        category = _make_category(shop, "List Color Missing Cat")
        product = _make_product(
            shop, category, "List Color Rice", barcode=PRIMARY_A
        )
        assert not hasattr(product, "color")

        api_client.force_authenticate(user=owner)
        listed = api_client.get(_list_url())

        assert listed.status_code == status.HTTP_200_OK
        row = _list_row(listed.data, product.id)
        assert "color" in row
        assert row["color"] is None
        assert row["name"] == product.name
        assert row["barcode"] == PRIMARY_A

    def test_serializer_echoes_color_when_attribute_exists(self):
        owner, shop = _make_retailer("list_color_echo_own", "List Color Echo Shop")
        category = _make_category(shop, "List Color Echo Cat")
        product = _make_product(shop, category, "List Color Atta")
        product.color = "navy"

        data = ProductListSerializer(product).data
        assert data["color"] == "navy"
        assert data["name"] == "List Color Atta"

    def test_serializer_null_passthrough_when_attribute_is_none(self):
        owner, shop = _make_retailer("list_color_null_own", "List Color Null Shop")
        category = _make_category(shop, "List Color Null Cat")
        product = _make_product(shop, category, "List Color Sugar")
        product.color = None

        assert ProductListSerializer(product).data["color"] is None

    def test_serializer_empty_passthrough(self):
        owner, shop = _make_retailer("list_color_empty_own", "List Color Empty Shop")
        category = _make_category(shop, "List Color Empty Cat")
        product = _make_product(shop, category, "List Color Salt")
        product.color = ""

        assert ProductListSerializer(product).data["color"] == ""

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("list_color_auth_own", "List Color Auth Shop")
        category = _make_category(shop, "List Color Auth Cat")
        _make_product(shop, category, "List Color Auth Rice", barcode=PRIMARY_A)
        customer = _make_customer("list_color_auth_cust")

        anon = api_client.get(_list_url())
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(_list_url())
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_list_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("list_color_ten_a", "List Color Tenant A")
        owner_b, shop_b = _make_retailer("list_color_ten_b", "List Color Tenant B")
        cat_a = _make_category(shop_a, "List Color A Cat")
        cat_b = _make_category(shop_b, "List Color B Cat")
        product_a = _make_product(shop_a, cat_a, "List Color A SKU", barcode=PRIMARY_A)
        product_b = _make_product(shop_b, cat_b, "List Color B SKU", barcode=PRIMARY_B)

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(_list_url())

        assert listed.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in _rows(listed.data)}
        assert product_a.id not in ids
        assert product_b.id in ids
        own = _list_row(listed.data, product_b.id)
        assert own["color"] is None
        assert own["name"] == product_b.name

    def test_list_color_adds_no_product_query(self):
        owner, shop = _make_retailer("list_color_n1_own", "List Color N1 Shop")
        category = _make_category(shop, "List Color N1 Cat")
        products = [
            _make_product(shop, category, f"List Color N1 {idx}")
            for idx in range(3)
        ]
        for product, value in zip(products, ("red", "blue", None)):
            product.color = value

        with CaptureQueriesContext(connection) as captured:
            data = ProductListSerializer(products, many=True).data

        assert [row["color"] for row in data] == ["red", "blue", None]
        assert _product_table_reads(captured) == []

    def test_public_list_color_null_when_product_has_no_field(self, api_client):
        _owner, shop = _make_retailer("list_color_pub_own", "List Color Public Shop")
        category = _make_category(shop, "List Color Public Cat")
        product = _make_product(
            shop, category, "List Color Public Mango", barcode=PRIMARY_B
        )
        assert not hasattr(product, "color")

        listed = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        assert listed.status_code == status.HTTP_200_OK
        row = _list_row(listed.data, product.id)
        assert "color" in row
        assert row["color"] is None
        assert row["name"] == product.name

    def test_product_search_serializer_meta_stays_without_color(self):
        assert "color" not in ProductSearchSerializer.Meta.fields

    def test_detail_and_pos_nopage_stay_without_color(self, api_client):
        assert "color" not in ProductDetailSerializer.Meta.fields

        owner, shop = _make_retailer("list_color_pos_own", "List Color POS Shop")
        category = _make_category(shop, "List Color POS Cat")
        product = _make_product(shop, category, "List Color POS Rice")

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK
        pos_row = _list_row(pos.data, product.id)
        assert "color" not in pos_row
