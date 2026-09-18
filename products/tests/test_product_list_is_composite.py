"""
Optional is_composite on the product list serializer.

Echo Product.is_composite when the attribute exists; otherwise null.
Do not add is_composite to any serializer Meta.fields. Product has no
is_composite column — do not invent one. Dummy / local only.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import FieldDoesNotExist
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
    ProductUpdateSerializer,
    product_is_composite,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8903611111111"
PRIMARY_B = "8903612222222"


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


def _public_list_url(retailer_id):
    return reverse("get_retailer_products_public", args=[retailer_id])


def _pos(api_client):
    return api_client.get(_list_url(), {"no_page": "true"})


def _assert_no_is_composite_meta(*serializer_classes):
    for serializer_cls in serializer_classes:
        assert "is_composite" not in serializer_cls.Meta.fields


def _product_table_reads(captured):
    return [
        q["sql"]
        for q in captured.captured_queries
        if 'FROM "product"' in q["sql"]
    ]


@pytest.mark.django_db
class TestProductIsCompositeHelper:
    def test_product_has_no_is_composite_field(self):
        with pytest.raises(FieldDoesNotExist):
            Product._meta.get_field("is_composite")

    def test_dummy_missing_attribute_is_null(self):
        assert product_is_composite(SimpleNamespace(name="no-flag")) is None
        assert product_is_composite(None) is None

    def test_dummy_true_and_false_are_echoed(self):
        assert product_is_composite(SimpleNamespace(is_composite=True)) is True
        assert product_is_composite(SimpleNamespace(is_composite=False)) is False

    def test_dummy_null_passthrough(self):
        assert product_is_composite(SimpleNamespace(is_composite=None)) is None


@pytest.mark.django_db
class TestProductListIsComposite:
    def test_list_is_composite_null_when_product_has_no_field(self, api_client):
        owner, shop = _make_retailer("list_comp_miss_own", "List Comp Missing Shop")
        category = _make_category(shop, "List Comp Missing Cat")
        product = _make_product(
            shop, category, "List Comp Rice", barcode=PRIMARY_A
        )
        assert not hasattr(product, "is_composite")

        api_client.force_authenticate(user=owner)
        listed = api_client.get(_list_url())
        public = api_client.get(_public_list_url(shop.id))

        assert listed.status_code == status.HTTP_200_OK
        assert public.status_code == status.HTTP_200_OK
        row = _list_row(listed.data, product.id)
        assert "is_composite" in row
        assert row["is_composite"] is None
        assert row["name"] == product.name
        assert row["barcode"] == PRIMARY_A
        public_row = _list_row(public.data, product.id)
        assert public_row["is_composite"] is None

    def test_serializer_echoes_dummy_flag_when_attribute_exists(self):
        owner, shop = _make_retailer("list_comp_echo_own", "List Comp Echo Shop")
        category = _make_category(shop, "List Comp Echo Cat")
        product = _make_product(shop, category, "List Comp Atta")
        product.is_composite = True

        data = ProductListSerializer(product).data
        assert data["is_composite"] is True
        assert data["name"] == "List Comp Atta"

    def test_serializer_false_stays_false(self):
        owner, shop = _make_retailer("list_comp_false_own", "List Comp False Shop")
        category = _make_category(shop, "List Comp False Cat")
        product = _make_product(shop, category, "List Comp Sugar")
        product.is_composite = False

        assert ProductListSerializer(product).data["is_composite"] is False

    def test_serializer_null_passthrough_when_attribute_is_none(self):
        owner, shop = _make_retailer("list_comp_null_own", "List Comp Null Shop")
        category = _make_category(shop, "List Comp Null Cat")
        product = _make_product(shop, category, "List Comp Salt")
        product.is_composite = None

        assert ProductListSerializer(product).data["is_composite"] is None

    def test_write_payload_is_composite_is_ignored(self, api_client):
        owner, shop = _make_retailer("list_comp_write_own", "List Comp Write Shop")
        category = _make_category(shop, "List Comp Write Cat")
        product = _make_product(shop, category, "List Comp Write Atta")

        api_client.force_authenticate(user=owner)
        updated = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"is_composite": True},
            format="json",
        )
        assert updated.status_code == status.HTTP_200_OK, updated.data
        product.refresh_from_db()
        assert not hasattr(product, "is_composite")
        write = ProductUpdateSerializer(
            product, data={"is_composite": True}, partial=True
        )
        assert write.is_valid(), write.errors
        write.save()
        product.refresh_from_db()
        assert not hasattr(product, "is_composite")

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("list_comp_auth_own", "List Comp Auth Shop")
        category = _make_category(shop, "List Comp Auth Cat")
        product = _make_product(
            shop, category, "List Comp Auth Rice", barcode=PRIMARY_A
        )
        customer = _make_customer("list_comp_auth_cust")

        anon = api_client.get(_list_url())
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(_list_url())
        assert denied.status_code == status.HTTP_403_FORBIDDEN

        api_client.force_authenticate(user=owner)
        own = api_client.get(_list_url())
        assert own.status_code == status.HTTP_200_OK
        assert _list_row(own.data, product.id)["is_composite"] is None

    def test_list_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("list_comp_ten_a", "List Comp Tenant A")
        owner_b, shop_b = _make_retailer("list_comp_ten_b", "List Comp Tenant B")
        cat_a = _make_category(shop_a, "List Comp A Cat")
        cat_b = _make_category(shop_b, "List Comp B Cat")
        product_a = _make_product(shop_a, cat_a, "List Comp A SKU", barcode=PRIMARY_A)
        product_b = _make_product(shop_b, cat_b, "List Comp B SKU", barcode=PRIMARY_B)

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(_list_url())

        assert listed.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in _rows(listed.data)}
        assert product_a.id not in ids
        assert product_b.id in ids
        own = _list_row(listed.data, product_b.id)
        assert own["is_composite"] is None
        assert own["name"] == product_b.name

    def test_list_is_composite_adds_no_product_query(self):
        owner, shop = _make_retailer("list_comp_n1_own", "List Comp N1 Shop")
        category = _make_category(shop, "List Comp N1 Cat")
        products = [
            _make_product(shop, category, f"List Comp N1 {idx}")
            for idx in range(3)
        ]
        for product, value in zip(products, (True, False, None)):
            product.is_composite = value

        with CaptureQueriesContext(connection) as captured:
            data = ProductListSerializer(products, many=True).data

        assert [row["is_composite"] for row in data] == [True, False, None]
        assert _product_table_reads(captured) == []

    def test_meta_stays_without_is_composite(self):
        _assert_no_is_composite_meta(
            ProductListSerializer,
            ProductSearchSerializer,
            ProductDetailSerializer,
        )

    def test_detail_search_and_pos_nopage_stay_without_is_composite(self, api_client):
        owner, shop = _make_retailer("list_comp_pos_own", "List Comp POS Shop")
        category = _make_category(shop, "List Comp POS Cat")
        product = _make_product(shop, category, "List Comp POS Rice")
        product.is_composite = True

        assert "is_composite" not in ProductDetailSerializer(product).data
        assert "is_composite" not in ProductSearchSerializer(product).data

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK
        pos_row = _list_row(pos.data, product.id)
        assert "is_composite" not in pos_row
