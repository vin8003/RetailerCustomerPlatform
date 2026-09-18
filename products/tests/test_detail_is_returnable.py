"""
OE-357 / F follow-on — optional is_returnable on product detail.

Optional is_returnable on product detail (if the attribute exists).

READ echo only. Missing field omits the key (do not invent false).
Present false stays false. ProductSearchSerializer Meta is unchanged.
Dummy shops only — never *.ordereasy.win.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import FieldDoesNotExist
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductBrand, ProductCategory
from products.serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    optional_is_returnable,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8903551111111"
STORE_ATTA = Decimal("20.00")


def _product_has_is_returnable_field():
    try:
        Product._meta.get_field("is_returnable")
        return True
    except FieldDoesNotExist:
        return False


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


def _make_brand(name):
    return ProductBrand.objects.create(name=name, is_active=True)


def _make_product(retailer, category, name, brand=None, barcode=None, **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "brand": brand,
        "barcode": barcode,
        "price": STORE_ATTA,
        "purchase_price": Decimal("10.00"),
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "piece",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


@pytest.mark.django_db
class TestOptionalIsReturnableHelper:
    def test_missing_attribute_is_none(self):
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

    def test_dummy_none_does_not_invent_false(self):
        class Dummy:
            is_returnable = None

        assert optional_is_returnable(Dummy()) is None


@pytest.mark.django_db
class TestProductDetailIsReturnable:
    def test_search_meta_omits_is_returnable(self):
        assert "is_returnable" not in ProductSearchSerializer.Meta.fields
        assert "is_returnable" not in ProductListSerializer.Meta.fields

    def test_real_product_follows_model_field(self):
        _owner, shop = _make_retailer("oe_ret_own", "Returnable Shop")
        category = _make_category(shop, "Groceries")
        brand = _make_brand("Dummy Brand")
        atta = _make_product(
            shop,
            category,
            "Dummy Atta",
            brand=brand,
            barcode=PRIMARY_A,
        )

        data = ProductDetailSerializer(atta).data
        if _product_has_is_returnable_field():
            assert "is_returnable" in data
            assert data["is_returnable"] is bool(atta.is_returnable)
        else:
            assert "is_returnable" not in data

        search_data = ProductSearchSerializer(atta).data
        assert "is_returnable" not in search_data
        list_data = ProductListSerializer(atta).data
        assert "is_returnable" not in list_data

    def test_dummy_true_echoes_on_detail_only(self):
        _owner, shop = _make_retailer("oe_ret_true", "Returnable True Shop")
        category = _make_category(shop, "Groceries")
        atta = _make_product(shop, category, "Dummy Returnable Atta")
        atta.is_returnable = True

        detail_data = ProductDetailSerializer(atta).data
        assert detail_data["is_returnable"] is True
        assert "is_returnable" not in ProductSearchSerializer(atta).data
        assert "is_returnable" not in ProductListSerializer(atta).data

    def test_dummy_false_stays_false_on_detail(self):
        _owner, shop = _make_retailer("oe_ret_false", "Returnable False Shop")
        category = _make_category(shop, "Groceries")
        atta = _make_product(shop, category, "Dummy Nonreturnable Atta")
        atta.is_returnable = False

        detail_data = ProductDetailSerializer(atta).data
        assert "is_returnable" in detail_data
        assert detail_data["is_returnable"] is False

    def test_retailer_detail_http_and_negatives(self, api_client):
        owner, shop = _make_retailer("oe_ret_http", "Returnable HTTP Shop")
        other, _other_shop = _make_retailer("oe_ret_other", "Other Shop")
        customer = _make_customer("oe_ret_cust")
        category = _make_category(shop, "Groceries")
        atta = _make_product(shop, category, "Dummy HTTP Atta", barcode=PRIMARY_A)

        unauth = api_client.get(reverse("get_product_detail", args=[atta.id]))
        assert unauth.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        forbidden = api_client.get(reverse("get_product_detail", args=[atta.id]))
        assert forbidden.status_code == status.HTTP_403_FORBIDDEN

        api_client.force_authenticate(user=other)
        missing = api_client.get(reverse("get_product_detail", args=[atta.id]))
        assert missing.status_code == status.HTTP_404_NOT_FOUND

        api_client.force_authenticate(user=owner)
        ok = api_client.get(reverse("get_product_detail", args=[atta.id]))
        assert ok.status_code == status.HTTP_200_OK
        assert ok.data["name"] == "Dummy HTTP Atta"
        if _product_has_is_returnable_field():
            assert isinstance(ok.data["is_returnable"], bool)
        else:
            assert "is_returnable" not in ok.data

        public = api_client.get(
            reverse("get_product_detail_public", args=[shop.id, atta.id])
        )
        assert public.status_code == status.HTTP_200_OK
        if _product_has_is_returnable_field():
            assert isinstance(public.data["is_returnable"], bool)
        else:
            assert "is_returnable" not in public.data
