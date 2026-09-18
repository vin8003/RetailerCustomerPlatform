"""
OE-357 / F follow-on — optional is_returnable on product detail.

Echo Product.is_returnable when the attribute exists; otherwise null.
Do not add is_returnable to any serializer Meta.fields. Product has no
is_returnable column — do not invent one. Dummy / local only.
Never *.ordereasy.win.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import FieldDoesNotExist
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
    optional_is_returnable,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

STORE_ATTA = Decimal("20.00")


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
        "price": STORE_ATTA,
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


def _assert_no_is_returnable_meta(*serializer_classes):
    for serializer_cls in serializer_classes:
        assert "is_returnable" not in serializer_cls.Meta.fields


@pytest.mark.django_db
class TestOptionalIsReturnableHelper:
    def test_product_has_no_is_returnable_field(self):
        with pytest.raises(FieldDoesNotExist):
            Product._meta.get_field("is_returnable")

    def test_helper_null_when_attribute_missing(self):
        assert optional_is_returnable(None) is None
        assert optional_is_returnable(object()) is None

    def test_dummy_true_and_false(self):
        class Dummy:
            pass

        dummy = Dummy()
        dummy.is_returnable = True
        assert optional_is_returnable(dummy) is True
        dummy.is_returnable = False
        assert optional_is_returnable(dummy) is False

    def test_dummy_none_stays_none(self):
        class Dummy:
            is_returnable = None

        assert optional_is_returnable(Dummy()) is None


@pytest.mark.django_db
class TestProductDetailIsReturnable:
    def test_search_list_detail_meta_omit_is_returnable(self):
        _assert_no_is_returnable_meta(
            ProductDetailSerializer,
            ProductListSerializer,
            ProductSearchSerializer,
            ProductUpdateSerializer,
            ProductCreateSerializer,
        )

    def test_missing_field_is_null_on_detail(self):
        _owner, shop = _make_retailer("oe357_miss_own", "OE357 Miss Shop")
        category = _make_category(shop, "Groceries")
        atta = _make_product(shop, category, "Dummy Atta")

        detail_data = ProductDetailSerializer(atta).data
        assert "is_returnable" in detail_data
        assert detail_data["is_returnable"] is None
        assert "is_returnable" not in ProductSearchSerializer(atta).data
        assert "is_returnable" not in ProductListSerializer(atta).data

    def test_dummy_true_echoes_on_detail_only(self):
        _owner, shop = _make_retailer("oe357_true_own", "OE357 True Shop")
        category = _make_category(shop, "Groceries")
        atta = _make_product(shop, category, "Dummy Returnable Atta")
        atta.is_returnable = True

        detail_data = ProductDetailSerializer(atta).data
        assert detail_data["is_returnable"] is True
        assert "is_returnable" not in ProductSearchSerializer(atta).data
        assert "is_returnable" not in ProductListSerializer(atta).data

    def test_dummy_false_stays_false_on_detail(self):
        _owner, shop = _make_retailer("oe357_false_own", "OE357 False Shop")
        category = _make_category(shop, "Groceries")
        atta = _make_product(shop, category, "Dummy Nonreturnable Atta")
        atta.is_returnable = False

        detail_data = ProductDetailSerializer(atta).data
        assert detail_data["is_returnable"] is False

    def test_write_is_returnable_is_ignored(self):
        _owner, shop = _make_retailer("oe357_write_own", "OE357 Write Shop")
        category = _make_category(shop, "Groceries")
        atta = _make_product(shop, category, "Dummy Write Atta")

        update = ProductUpdateSerializer(
            atta,
            data={"is_returnable": True, "name": "Dummy Write Atta"},
            partial=True,
        )
        assert update.is_valid(), update.errors
        update.save()
        refreshed = Product.objects.get(pk=atta.pk)
        assert optional_is_returnable(refreshed) is None

        create = ProductCreateSerializer(
            data={
                "name": "Dummy Created Atta",
                "price": "12.00",
                "category": category.id,
                "quantity": 4,
                "is_returnable": True,
            },
            context={"retailer": shop},
        )
        assert create.is_valid(), create.errors
        created = create.save()
        assert optional_is_returnable(Product.objects.get(pk=created.pk)) is None

    def test_retailer_detail_http_and_negatives(self, api_client):
        owner, shop = _make_retailer("oe357_http_own", "OE357 HTTP Shop")
        other, _other_shop = _make_retailer("oe357_http_other", "OE357 Other Shop")
        customer = _make_customer("oe357_http_cust")
        category = _make_category(shop, "Groceries")
        atta = _make_product(shop, category, "Dummy HTTP Atta")

        unauth = api_client.get(_detail_url(atta.id))
        assert unauth.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        forbidden = api_client.get(_detail_url(atta.id))
        assert forbidden.status_code == status.HTTP_403_FORBIDDEN

        api_client.force_authenticate(user=other)
        missing = api_client.get(_detail_url(atta.id))
        assert missing.status_code == status.HTTP_404_NOT_FOUND

        api_client.force_authenticate(user=owner)
        ok = api_client.get(_detail_url(atta.id))
        assert ok.status_code == status.HTTP_200_OK
        assert ok.data["name"] == "Dummy HTTP Atta"
        assert ok.data["is_returnable"] is None

        public = api_client.get(_public_detail_url(shop.id, atta.id))
        assert public.status_code == status.HTTP_200_OK
        assert public.data["is_returnable"] is None
