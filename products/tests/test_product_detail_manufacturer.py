"""
Optional manufacturer on product detail.

Echo Product.manufacturer when the attribute exists; otherwise null.
Do not add manufacturer to any serializer Meta.fields. Product has no
manufacturer column — do not invent one. Dummy / local only.
"""
from decimal import Decimal

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
    product_manufacturer,
)
from retailers.models import RetailerProfile
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


def _detail_url(product_id):
    return reverse("get_product_detail", args=[product_id])


def _public_detail_url(retailer_id, product_id):
    return reverse("get_product_detail_public", args=[retailer_id, product_id])


def _assert_no_manufacturer_meta(*serializer_classes):
    for serializer_cls in serializer_classes:
        assert "manufacturer" not in serializer_cls.Meta.fields


@pytest.mark.django_db
class TestProductDetailManufacturer:
    def test_product_has_no_manufacturer_field(self):
        with pytest.raises(FieldDoesNotExist):
            Product._meta.get_field("manufacturer")

    def test_helper_null_when_attribute_missing(self):
        _owner, shop = _make_retailer("mfg_help_own", "Mfg Helper Shop")
        category = _make_category(shop, "Mfg Helper Cat")
        product = _make_product(shop, category, "Mfg Helper Rice")
        assert not hasattr(product, "manufacturer")
        assert product_manufacturer(product) is None
        assert product_manufacturer(None) is None

    def test_helper_echoes_when_attribute_exists(self):
        _owner, shop = _make_retailer("mfg_echo_own", "Mfg Echo Shop")
        category = _make_category(shop, "Mfg Echo Cat")
        product = _make_product(shop, category, "Mfg Echo Atta")
        product.manufacturer = "Dummy Mills Co"
        assert product_manufacturer(product) == "Dummy Mills Co"

    def test_helper_null_and_empty_passthrough(self):
        _owner, shop = _make_retailer("mfg_pass_own", "Mfg Pass Shop")
        category = _make_category(shop, "Mfg Pass Cat")
        product = _make_product(shop, category, "Mfg Pass Sugar")
        product.manufacturer = None
        assert product_manufacturer(product) is None
        product.manufacturer = ""
        assert product_manufacturer(product) == ""

    def test_detail_includes_null_when_field_missing(self, api_client):
        owner, shop = _make_retailer("mfg_miss_own", "Mfg Missing Shop")
        category = _make_category(shop, "Mfg Missing Cat")
        product = _make_product(shop, category, "Mfg Missing Rice")

        api_client.force_authenticate(user=owner)
        retailer_detail = api_client.get(_detail_url(product.id))
        assert retailer_detail.status_code == status.HTTP_200_OK
        assert retailer_detail.data["name"] == product.name
        assert retailer_detail.data["manufacturer"] is None
        assert "manufacturer" in ProductDetailSerializer(product).data

        api_client.force_authenticate(user=None)
        public_detail = api_client.get(_public_detail_url(shop.id, product.id))
        assert public_detail.status_code == status.HTTP_200_OK
        assert public_detail.data["name"] == product.name
        assert public_detail.data["manufacturer"] is None

    def test_serializer_echoes_when_attribute_exists(self):
        _owner, shop = _make_retailer("mfg_ser_own", "Mfg Ser Shop")
        category = _make_category(shop, "Mfg Ser Cat")
        product = _make_product(shop, category, "Mfg Ser Atta")
        product.manufacturer = "Dummy Foods Ltd"

        data = ProductDetailSerializer(product).data
        assert data["manufacturer"] == "Dummy Foods Ltd"
        assert data["name"] == "Mfg Ser Atta"

    def test_serializer_null_passthrough_when_attribute_is_none(self):
        _owner, shop = _make_retailer("mfg_null_own", "Mfg Null Shop")
        category = _make_category(shop, "Mfg Null Cat")
        product = _make_product(shop, category, "Mfg Null Sugar")
        product.manufacturer = None
        assert ProductDetailSerializer(product).data["manufacturer"] is None

    def test_serializer_empty_passthrough(self):
        _owner, shop = _make_retailer("mfg_empty_own", "Mfg Empty Shop")
        category = _make_category(shop, "Mfg Empty Cat")
        product = _make_product(shop, category, "Mfg Empty Salt")
        product.manufacturer = ""
        assert ProductDetailSerializer(product).data["manufacturer"] == ""

    def test_write_payload_manufacturer_is_ignored(self, api_client):
        owner, shop = _make_retailer("mfg_write_own", "Mfg Write Shop")
        category = _make_category(shop, "Mfg Write Cat")
        product = _make_product(shop, category, "Mfg Write Atta")
        sku_name = product.name
        sku_price = product.price

        api_client.force_authenticate(user=owner)
        updated = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"manufacturer": "Should Not Persist"},
            format="json",
        )
        assert updated.status_code == status.HTTP_200_OK, updated.data
        assert updated.data["id"] == product.id
        assert updated.data["name"] == sku_name
        assert Decimal(str(updated.data["price"])) == sku_price
        assert updated.data["manufacturer"] is None
        product.refresh_from_db()
        assert product.id == updated.data["id"]
        assert product.name == sku_name
        assert product.price == sku_price
        assert not hasattr(product, "manufacturer")
        write = ProductUpdateSerializer(
            product, data={"manufacturer": "Ignored"}, partial=True
        )
        assert write.is_valid(), write.errors
        write.save()
        product.refresh_from_db()
        assert product.name == sku_name
        assert product.price == sku_price
        assert not hasattr(product, "manufacturer")

        created = api_client.post(
            reverse("create_product"),
            {
                "name": "Mfg Write Create Rice",
                "price": "15.00",
                "category": category.id,
                "quantity": 4,
                "manufacturer": "Should Not Persist",
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        assert created.data["name"] == "Mfg Write Create Rice"
        assert created.data["manufacturer"] is None
        created_product = Product.objects.get(id=created.data["id"])
        assert created_product.name == "Mfg Write Create Rice"
        assert created_product.price == Decimal("15.00")
        assert not hasattr(created_product, "manufacturer")

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("mfg_auth_own", "Mfg Auth Shop")
        category = _make_category(shop, "Mfg Auth Cat")
        product = _make_product(shop, category, "Mfg Auth Rice")
        customer = _make_customer("mfg_auth_cust")

        anon = api_client.get(_detail_url(product.id))
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(_detail_url(product.id))
        assert denied.status_code == status.HTTP_403_FORBIDDEN

        api_client.force_authenticate(user=owner)
        own = api_client.get(_detail_url(product.id))
        assert own.status_code == status.HTTP_200_OK
        assert own.data["manufacturer"] is None

    def test_product_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("mfg_ten_a", "Mfg Tenant A")
        owner_b, shop_b = _make_retailer("mfg_ten_b", "Mfg Tenant B")
        cat_a = _make_category(shop_a, "Mfg A Cat")
        cat_b = _make_category(shop_b, "Mfg B Cat")
        product_a = _make_product(shop_a, cat_a, "Mfg A SKU")
        product_b = _make_product(shop_b, cat_b, "Mfg B SKU")

        api_client.force_authenticate(user=owner_b)
        foreign = api_client.get(_detail_url(product_a.id))
        own = api_client.get(_detail_url(product_b.id))

        assert foreign.status_code == status.HTTP_404_NOT_FOUND
        assert own.status_code == status.HTTP_200_OK
        assert own.data["id"] == product_b.id
        assert own.data["manufacturer"] is None

    def test_serializer_adds_no_manufacturer_query(self):
        _owner, shop = _make_retailer("mfg_n1_own", "Mfg N1 Shop")
        category = _make_category(shop, "Mfg N1 Cat")
        product = _make_product(shop, category, "Mfg N1 Sugar")
        loaded = Product.objects.select_related(
            "retailer", "category", "brand"
        ).get(pk=product.id)
        loaded.manufacturer = "Dummy Query Mills"

        with CaptureQueriesContext(connection) as captured:
            data = ProductDetailSerializer(
                loaded,
                context={
                    "active_offers": [],
                    "wishlisted_product_ids": [],
                },
            ).data

        assert data["manufacturer"] == "Dummy Query Mills"
        sql = " ".join(query["sql"] for query in captured)
        assert "manufacturer" not in sql.lower()

    def test_list_and_search_meta_stay_without_manufacturer(self):
        _assert_no_manufacturer_meta(
            ProductListSerializer,
            ProductSearchSerializer,
            ProductDetailSerializer,
        )
        _owner, shop = _make_retailer("mfg_meta_own", "Mfg Meta Shop")
        category = _make_category(shop, "Mfg Meta Cat")
        product = _make_product(shop, category, "Mfg Meta Rice")
        product.manufacturer = "Dummy Meta Mills"

        assert "manufacturer" not in ProductListSerializer(product).data
        assert "manufacturer" not in ProductSearchSerializer(product).data
        assert ProductDetailSerializer(product).data["manufacturer"] == (
            "Dummy Meta Mills"
        )
