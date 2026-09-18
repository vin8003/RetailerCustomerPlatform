"""
Optional net_weight on product catalog reads.

Echo Product.net_weight only when the attribute exists. Missing field or
null stays null (no invented weight). Auth/tenancy unchanged. READ only.
Does not touch ProductSearchSerializer Meta, POS views, or write serializers.
Dummy / local only — never *.ordereasy.win.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory
from products.serializers import (
    ProductCreateSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    ProductUpdateSerializer,
    product_net_weight,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

NET_WEIGHT_ATTA = Decimal("0.500")
NET_WEIGHT_RICE = Decimal("5.000")


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
        "unit": "kg",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _as_weight(value):
    if value is None:
        return None
    return Decimal(str(value))


@pytest.mark.django_db
class TestProductNetWeightHelper:
    def test_missing_attribute_is_null(self):
        assert not hasattr(Product, "net_weight")
        assert product_net_weight(SimpleNamespace(name="no-weight")) is None

    def test_none_product_is_null(self):
        assert product_net_weight(None) is None

    def test_present_value_is_echoed(self):
        dummy = SimpleNamespace(net_weight=NET_WEIGHT_ATTA)
        assert product_net_weight(dummy) == NET_WEIGHT_ATTA

    def test_null_passthrough(self):
        assert product_net_weight(SimpleNamespace(net_weight=None)) is None


@pytest.mark.django_db
class TestProductNetWeightAvoidsMeta:
    def test_catalog_meta_does_not_declare_net_weight(self):
        for serializer_cls in (
            ProductListSerializer,
            ProductSearchSerializer,
            ProductDetailSerializer,
            ProductCreateSerializer,
            ProductUpdateSerializer,
        ):
            assert "net_weight" not in serializer_cls.Meta.fields


@pytest.mark.django_db
class TestProductNetWeightSerializers:
    def test_missing_field_is_null_on_list_search_detail(self):
        _owner, shop = _make_retailer("nw_miss_own", "NW Missing Shop")
        category = _make_category(shop, "NW Missing Cat")
        product = _make_product(shop, category, "NW Rice")
        assert not hasattr(product, "net_weight")

        for serializer_cls in (
            ProductListSerializer,
            ProductSearchSerializer,
            ProductDetailSerializer,
        ):
            data = serializer_cls(product).data
            assert "net_weight" in data
            assert data["net_weight"] is None
            assert data["name"] == "NW Rice"

    def test_serializer_echoes_weight_when_attribute_exists(self):
        _owner, shop = _make_retailer("nw_echo_own", "NW Echo Shop")
        category = _make_category(shop, "NW Echo Cat")
        product = _make_product(shop, category, "NW Atta")
        product.net_weight = NET_WEIGHT_ATTA

        for serializer_cls in (
            ProductListSerializer,
            ProductSearchSerializer,
            ProductDetailSerializer,
        ):
            data = serializer_cls(product).data
            assert _as_weight(data["net_weight"]) == NET_WEIGHT_ATTA

    def test_serializer_null_passthrough_when_attribute_is_none(self):
        _owner, shop = _make_retailer("nw_null_own", "NW Null Shop")
        category = _make_category(shop, "NW Null Cat")
        product = _make_product(shop, category, "NW Sugar")
        product.net_weight = None

        for serializer_cls in (
            ProductListSerializer,
            ProductSearchSerializer,
            ProductDetailSerializer,
        ):
            assert serializer_cls(product).data["net_weight"] is None

    def test_create_payload_net_weight_is_ignored(self):
        _owner, shop = _make_retailer("nw_write_own", "NW Write Shop")
        category = _make_category(shop, "NW Write Cat")
        serializer = ProductCreateSerializer(
            data={
                "name": "NW Dummy Create",
                "price": "12.00",
                "category": category.id,
                "quantity": "4.000",
                "unit": "kg",
                "net_weight": "9.999",
            },
            context={"retailer": shop},
        )
        assert serializer.is_valid(), serializer.errors
        created = serializer.save()
        assert not hasattr(created, "net_weight")
        created.refresh_from_db()
        assert not hasattr(created, "net_weight")


@pytest.mark.django_db
class TestProductNetWeightReads:
    def test_list_search_detail_null_when_product_has_no_field(self, api_client):
        owner, shop = _make_retailer("nw_api_miss_own", "NW API Missing Shop")
        category = _make_category(shop, "NW API Missing Cat")
        product = _make_product(shop, category, "NW API Rice")

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        search = api_client.get(reverse("search_products"), {"search": "NW API"})
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))

        assert listed.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        list_row = _row_by_id(listed.data, product.id)
        search_row = _row_by_id(search.data, product.id)
        for row in (list_row, search_row, detail.data):
            assert "net_weight" in row
            assert row["net_weight"] is None

    def test_unauthenticated_retailer_reads_denied(self, api_client):
        listed = api_client.get(reverse("get_retailer_products"))
        search = api_client.get(reverse("search_products"), {"search": "NW"})
        assert listed.status_code == status.HTTP_401_UNAUTHORIZED
        assert search.status_code == status.HTTP_401_UNAUTHORIZED

    def test_customer_cannot_use_retailer_search(self, api_client):
        customer = _make_customer("nw_api_cust")
        api_client.force_authenticate(user=customer)
        search = api_client.get(reverse("search_products"), {"search": "NW"})
        assert search.status_code == status.HTTP_403_FORBIDDEN

    def test_public_list_and_search_include_null_net_weight(self, api_client):
        _owner, shop = _make_retailer("nw_pub_own", "NW Public Shop")
        category = _make_category(shop, "NW Public Cat")
        product = _make_product(shop, category, "NW Public Milk")

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "NW Public"},
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK
        public_row = _row_by_id(public.data, product.id)
        search_row = _row_by_id(public_search.data, product.id)
        assert public_row["net_weight"] is None
        assert search_row["net_weight"] is None

    def test_shop_scoped_list_hides_other_tenant(self, api_client):
        owner_a, shop_a = _make_retailer("nw_api_a_own", "NW Shop A")
        _owner_b, shop_b = _make_retailer("nw_api_b_own", "NW Shop B")
        cat_a = _make_category(shop_a, "NW Cat A")
        cat_b = _make_category(shop_b, "NW Cat B")
        product_a = _make_product(shop_a, cat_a, "NW Tenant A Rice")
        product_b = _make_product(shop_b, cat_b, "NW Tenant B Rice")

        api_client.force_authenticate(user=owner_a)
        listed = api_client.get(reverse("get_retailer_products"))
        assert listed.status_code == status.HTTP_200_OK
        ids = {
            row["id"]
            for row in (
                listed.data if isinstance(listed.data, list) else listed.data.get("results") or []
            )
        }
        assert product_a.id in ids
        assert product_b.id not in ids
