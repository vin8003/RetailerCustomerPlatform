"""
Optional track_batch on Product list serializer.

Echo Product.track_batch only when the attribute exists. Missing field
or null stays null (do not invent from has_batches). False stays false.
Auth/tenancy unchanged. READ only. Does not touch Meta.fields,
ProductSearchSerializer Meta, POS no_page, or detail.
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
    product_track_batch,
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
class TestProductTrackBatchHelper:
    def test_missing_attribute_is_null(self):
        assert not hasattr(Product, "track_batch")
        assert product_track_batch(SimpleNamespace(name="no-track-batch")) is None

    def test_none_product_is_null(self):
        assert product_track_batch(None) is None

    def test_present_true_is_echoed(self):
        assert product_track_batch(SimpleNamespace(track_batch=True)) is True

    def test_present_false_stays_false(self):
        assert product_track_batch(SimpleNamespace(track_batch=False)) is False

    def test_null_passthrough(self):
        assert product_track_batch(SimpleNamespace(track_batch=None)) is None

    def test_does_not_invent_from_has_batches(self):
        dummy = SimpleNamespace(has_batches=True)
        assert not hasattr(dummy, "track_batch")
        assert product_track_batch(dummy) is None


@pytest.mark.django_db
class TestProductListTrackBatch:
    def test_list_track_batch_null_when_product_has_no_field(self, api_client):
        owner, shop = _make_retailer(
            "list_tb_miss_own", "List Track Batch Missing Shop"
        )
        category = _make_category(shop, "List Track Batch Missing Cat")
        product = _make_product(
            shop, category, "List Track Batch Rice", barcode=PRIMARY_A
        )
        assert not hasattr(product, "track_batch")
        assert product.has_batches is False

        api_client.force_authenticate(user=owner)
        listed = api_client.get(_list_url())

        assert listed.status_code == status.HTTP_200_OK
        row = _list_row(listed.data, product.id)
        assert "track_batch" in row
        assert row["track_batch"] is None
        assert row["name"] == product.name
        assert row["barcode"] == PRIMARY_A
        assert row["has_batches"] is False

    def test_list_does_not_invent_track_batch_from_has_batches(self, api_client):
        owner, shop = _make_retailer(
            "list_tb_has_own", "List Track Batch HasBatches Shop"
        )
        category = _make_category(shop, "List Track Batch HasBatches Cat")
        product = _make_product(
            shop,
            category,
            "List Track Batch Atta",
            barcode=PRIMARY_B,
            has_batches=True,
        )
        assert product.has_batches is True
        assert not hasattr(product, "track_batch")

        api_client.force_authenticate(user=owner)
        listed = api_client.get(_list_url())

        assert listed.status_code == status.HTTP_200_OK
        row = _list_row(listed.data, product.id)
        assert row["has_batches"] is True
        assert row["track_batch"] is None

    def test_serializer_echoes_track_batch_when_attribute_exists(self):
        owner, shop = _make_retailer("list_tb_echo_own", "List Track Batch Echo Shop")
        category = _make_category(shop, "List Track Batch Echo Cat")
        product = _make_product(shop, category, "List Track Batch Sugar")
        product.track_batch = True

        data = ProductListSerializer(product).data
        assert data["track_batch"] is True
        assert data["name"] == "List Track Batch Sugar"

    def test_serializer_false_stays_false_when_attribute_exists(self):
        owner, shop = _make_retailer(
            "list_tb_false_own", "List Track Batch False Shop"
        )
        category = _make_category(shop, "List Track Batch False Cat")
        product = _make_product(shop, category, "List Track Batch Salt")
        product.track_batch = False

        data = ProductListSerializer(product).data
        assert "track_batch" in data
        assert data["track_batch"] is False

    def test_serializer_null_passthrough_when_attribute_is_none(self):
        owner, shop = _make_retailer("list_tb_null_own", "List Track Batch Null Shop")
        category = _make_category(shop, "List Track Batch Null Cat")
        product = _make_product(shop, category, "List Track Batch Oil")
        product.track_batch = None

        assert ProductListSerializer(product).data["track_batch"] is None

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("list_tb_auth_own", "List Track Batch Auth Shop")
        category = _make_category(shop, "List Track Batch Auth Cat")
        _make_product(shop, category, "List Track Batch Auth Rice", barcode=PRIMARY_A)
        customer = _make_customer("list_tb_auth_cust")

        anon = api_client.get(_list_url())
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(_list_url())
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_list_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("list_tb_ten_a", "List Track Batch Tenant A")
        owner_b, shop_b = _make_retailer("list_tb_ten_b", "List Track Batch Tenant B")
        cat_a = _make_category(shop_a, "List Track Batch A Cat")
        cat_b = _make_category(shop_b, "List Track Batch B Cat")
        product_a = _make_product(
            shop_a, cat_a, "List Track Batch A SKU", barcode=PRIMARY_A
        )
        product_b = _make_product(
            shop_b, cat_b, "List Track Batch B SKU", barcode=PRIMARY_B
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(_list_url())

        assert listed.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in _rows(listed.data)}
        assert product_a.id not in ids
        assert product_b.id in ids
        own = _list_row(listed.data, product_b.id)
        assert own["track_batch"] is None
        assert own["name"] == product_b.name

    def test_list_track_batch_adds_no_product_query(self):
        owner, shop = _make_retailer("list_tb_n1_own", "List Track Batch N1 Shop")
        category = _make_category(shop, "List Track Batch N1 Cat")
        products = [
            _make_product(shop, category, f"List Track Batch N1 {idx}")
            for idx in range(3)
        ]
        for product, value in zip(products, (True, False, None)):
            product.track_batch = value

        with CaptureQueriesContext(connection) as captured:
            data = ProductListSerializer(products, many=True).data

        assert [row["track_batch"] for row in data] == [True, False, None]
        assert _product_table_reads(captured) == []

    def test_list_search_and_detail_meta_stay_without_track_batch(self):
        assert "track_batch" not in ProductListSerializer.Meta.fields
        assert "track_batch" not in ProductSearchSerializer.Meta.fields
        assert "track_batch" not in ProductDetailSerializer.Meta.fields

    def test_detail_and_pos_nopage_stay_without_track_batch(self, api_client):
        owner, shop = _make_retailer("list_tb_pos_own", "List Track Batch POS Shop")
        category = _make_category(shop, "List Track Batch POS Cat")
        product = _make_product(shop, category, "List Track Batch POS Rice")

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK
        pos_row = _list_row(pos.data, product.id)
        assert "track_batch" not in pos_row

        detail = ProductDetailSerializer(product).data
        assert "track_batch" not in detail
