"""
Optional is_serialized on Product list serializer.

Echo Product.is_serialized only when the attribute exists. Missing
field or null stays null (no invented True). False stays false.
Auth/tenancy unchanged. READ only.

Avoid ProductSearchSerializer Meta, POS no_page, and detail Meta.
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
    product_is_serialized,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8903551111111"
PRIMARY_B = "8903552222222"


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
class TestProductIsSerializedHelper:
    def test_missing_attribute_is_null(self):
        assert not hasattr(Product, "is_serialized")
        assert product_is_serialized(SimpleNamespace(name="no-serialized")) is None

    def test_none_product_is_null(self):
        assert product_is_serialized(None) is None

    def test_present_true_is_echoed(self):
        assert product_is_serialized(SimpleNamespace(is_serialized=True)) is True

    def test_present_false_stays_false(self):
        assert product_is_serialized(SimpleNamespace(is_serialized=False)) is False

    def test_null_passthrough(self):
        assert product_is_serialized(SimpleNamespace(is_serialized=None)) is None


@pytest.mark.django_db
class TestProductListIsSerialized:
    def test_list_is_serialized_null_when_product_has_no_field(self, api_client):
        owner, shop = _make_retailer(
            "list_serialized_miss_own", "List Serialized Missing Shop"
        )
        category = _make_category(shop, "List Serialized Missing Cat")
        product = _make_product(
            shop, category, "List Serialized Rice", barcode=PRIMARY_A
        )
        assert not hasattr(product, "is_serialized")

        api_client.force_authenticate(user=owner)
        listed = api_client.get(_list_url())

        assert listed.status_code == status.HTTP_200_OK
        row = _list_row(listed.data, product.id)
        assert "is_serialized" in row
        assert row["is_serialized"] is None
        assert row["name"] == product.name
        assert row["barcode"] == PRIMARY_A

    def test_serializer_echoes_is_serialized_when_attribute_exists(self):
        owner, shop = _make_retailer(
            "list_serialized_echo_own", "List Serialized Echo Shop"
        )
        category = _make_category(shop, "List Serialized Echo Cat")
        product = _make_product(shop, category, "List Serialized Atta")
        product.is_serialized = True

        data = ProductListSerializer(product).data
        assert data["is_serialized"] is True
        assert data["name"] == "List Serialized Atta"

    def test_serializer_false_stays_false(self):
        owner, shop = _make_retailer(
            "list_serialized_false_own", "List Serialized False Shop"
        )
        category = _make_category(shop, "List Serialized False Cat")
        product = _make_product(shop, category, "List Serialized Sugar")
        product.is_serialized = False

        assert ProductListSerializer(product).data["is_serialized"] is False

    def test_serializer_null_passthrough_when_attribute_is_none(self):
        owner, shop = _make_retailer(
            "list_serialized_null_own", "List Serialized Null Shop"
        )
        category = _make_category(shop, "List Serialized Null Cat")
        product = _make_product(shop, category, "List Serialized Salt")
        product.is_serialized = None

        assert ProductListSerializer(product).data["is_serialized"] is None

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer(
            "list_serialized_auth_own", "List Serialized Auth Shop"
        )
        category = _make_category(shop, "List Serialized Auth Cat")
        _make_product(shop, category, "List Serialized Auth Rice", barcode=PRIMARY_A)
        customer = _make_customer("list_serialized_auth_cust")

        anon = api_client.get(_list_url())
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(_list_url())
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_list_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer(
            "list_serialized_ten_a", "List Serialized Tenant A"
        )
        owner_b, shop_b = _make_retailer(
            "list_serialized_ten_b", "List Serialized Tenant B"
        )
        cat_a = _make_category(shop_a, "List Serialized A Cat")
        cat_b = _make_category(shop_b, "List Serialized B Cat")
        product_a = _make_product(
            shop_a, cat_a, "List Serialized A SKU", barcode=PRIMARY_A
        )
        product_b = _make_product(
            shop_b, cat_b, "List Serialized B SKU", barcode=PRIMARY_B
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(_list_url())

        assert listed.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in _rows(listed.data)}
        assert product_a.id not in ids
        assert product_b.id in ids
        own = _list_row(listed.data, product_b.id)
        assert own["is_serialized"] is None
        assert own["name"] == product_b.name

    def test_list_is_serialized_adds_no_product_query(self):
        owner, shop = _make_retailer(
            "list_serialized_n1_own", "List Serialized N1 Shop"
        )
        category = _make_category(shop, "List Serialized N1 Cat")
        products = [
            _make_product(shop, category, f"List Serialized N1 {idx}")
            for idx in range(3)
        ]
        for product, value in zip(products, (True, False, None)):
            product.is_serialized = value

        with CaptureQueriesContext(connection) as captured:
            data = ProductListSerializer(products, many=True).data

        assert [row["is_serialized"] for row in data] == [True, False, None]
        assert _product_table_reads(captured) == []

    def test_product_search_serializer_meta_stays_without_is_serialized(self):
        assert "is_serialized" not in ProductSearchSerializer.Meta.fields

    def test_detail_and_pos_nopage_stay_without_is_serialized(self, api_client):
        assert "is_serialized" not in ProductDetailSerializer.Meta.fields

        owner, shop = _make_retailer(
            "list_serialized_pos_own", "List Serialized POS Shop"
        )
        category = _make_category(shop, "List Serialized POS Cat")
        product = _make_product(shop, category, "List Serialized POS Rice")

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK
        pos_row = _list_row(pos.data, product.id)
        assert "is_serialized" not in pos_row
