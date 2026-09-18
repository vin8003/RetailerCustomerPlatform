"""
KAN-276 — optional is_perishable on product read serializers.

Echo only when Product has the model field. Do not add Meta.fields
(ModelSerializer would crash if the column is absent). Dummy hosts only.
No live *.ordereasy.win.
"""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import FieldDoesNotExist
from django.urls import reverse
from rest_framework import serializers, status

from authentication.models import User
from products.models import Product, ProductCategory
from products.serializers import (
    OptionalIsPerishableReadMixin,
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    product_model_has_is_perishable,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

DUMMY_IMAGE_URL = "https://cdn.example.test/dummy-milk.jpg"
LIVE_HOST_NEEDLE = "ordereasy.win"

READ_SERIALIZERS = (
    ProductListSerializer,
    ProductDetailSerializer,
    ProductSearchSerializer,
)


class _DummyPerishableSerializer(OptionalIsPerishableReadMixin, serializers.Serializer):
    name = serializers.CharField()


def _make_retailer(username, shop_name):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    profile = RetailerProfile.objects.create(
        user=user,
        shop_name=shop_name,
        address_line1="1 Dummy Lane",
        city="DummyCity",
        state="DummyState",
        pincode="110001",
        is_active=True,
    )
    ensure_organization_for_profile(profile, name=f"{shop_name} Org")
    return user, profile


def _make_category(retailer, name):
    return ProductCategory.objects.create(name=name, retailer=retailer)


def _make_dummy_product(retailer, category, name, **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "price": Decimal("20.00"),
        "quantity": 10,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "kg",
        "image_url": DUMMY_IMAGE_URL,
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _payload_text(data):
    return json.dumps(data, default=str)


def _assert_no_live_host(data):
    assert LIVE_HOST_NEEDLE not in _payload_text(data)


@pytest.mark.django_db
class TestOptionalIsPerishableHelper:
    def test_model_field_is_absent_today(self):
        with pytest.raises(FieldDoesNotExist):
            Product._meta.get_field("is_perishable")
        assert product_model_has_is_perishable() is False


class TestOptionalIsPerishableMixinDummy:
    def test_dummy_omits_key_when_model_field_missing(self, monkeypatch):
        monkeypatch.setattr(
            "products.serializers.product_model_has_is_perishable",
            lambda: False,
        )
        dummy = SimpleNamespace(name="Rice", is_perishable=True)
        data = _DummyPerishableSerializer(dummy).data
        assert "is_perishable" not in data
        _assert_no_live_host(data)

    def test_dummy_true_when_model_field_exists(self, monkeypatch):
        monkeypatch.setattr(
            "products.serializers.product_model_has_is_perishable",
            lambda: True,
        )
        dummy = SimpleNamespace(name="Milk", is_perishable=True)
        assert _DummyPerishableSerializer(dummy).data["is_perishable"] is True

    def test_dummy_false_stays_false(self, monkeypatch):
        monkeypatch.setattr(
            "products.serializers.product_model_has_is_perishable",
            lambda: True,
        )
        dummy = SimpleNamespace(name="Cans", is_perishable=False)
        data = _DummyPerishableSerializer(dummy).data
        assert "is_perishable" in data
        assert data["is_perishable"] is False


@pytest.mark.django_db
class TestOptionalIsPerishableSerializers:
    @pytest.mark.parametrize("serializer_cls", READ_SERIALIZERS)
    def test_meta_fields_omit_is_perishable(self, serializer_cls):
        assert "is_perishable" not in serializer_cls.Meta.fields

    @pytest.mark.parametrize("serializer_cls", READ_SERIALIZERS)
    def test_omits_key_when_model_field_missing(
        self, serializer_cls, product, monkeypatch
    ):
        monkeypatch.setattr(
            "products.serializers.product_model_has_is_perishable",
            lambda: False,
        )
        product.image_url = DUMMY_IMAGE_URL
        product.save(update_fields=["image_url"])
        product.is_perishable = True

        data = serializer_cls(product).data
        assert "is_perishable" not in data
        _assert_no_live_host(data)
        assert DUMMY_IMAGE_URL in _payload_text(data)

    @pytest.mark.parametrize("serializer_cls", READ_SERIALIZERS)
    def test_echoes_true_when_model_field_exists(
        self, serializer_cls, product, monkeypatch
    ):
        monkeypatch.setattr(
            "products.serializers.product_model_has_is_perishable",
            lambda: True,
        )
        product.image_url = DUMMY_IMAGE_URL
        product.is_perishable = True

        data = serializer_cls(product).data
        assert data["is_perishable"] is True
        _assert_no_live_host(data)

    @pytest.mark.parametrize("serializer_cls", READ_SERIALIZERS)
    def test_false_stays_false_when_model_field_exists(
        self, serializer_cls, product, monkeypatch
    ):
        monkeypatch.setattr(
            "products.serializers.product_model_has_is_perishable",
            lambda: True,
        )
        product.is_perishable = False

        data = serializer_cls(product).data
        assert "is_perishable" in data
        assert data["is_perishable"] is False
        _assert_no_live_host(data)

    @pytest.mark.parametrize("serializer_cls", READ_SERIALIZERS)
    def test_missing_instance_attr_defaults_false(
        self, serializer_cls, product, monkeypatch
    ):
        monkeypatch.setattr(
            "products.serializers.product_model_has_is_perishable",
            lambda: True,
        )
        assert not hasattr(product, "is_perishable")

        data = serializer_cls(product).data
        assert data["is_perishable"] is False


@pytest.mark.django_db
class TestOptionalIsPerishableHttpSmoke:
    def test_retailer_list_and_search_omit_key_and_stay_dummy(
        self, api_client, monkeypatch
    ):
        monkeypatch.setattr(
            "products.serializers.product_model_has_is_perishable",
            lambda: False,
        )
        owner, shop = _make_retailer("isp_list_own", "ISP Dummy Shop")
        category = _make_category(shop, "ISP Dummy Cat")
        sku = _make_dummy_product(shop, category, "ISP Dummy Milk")

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        search = api_client.get(reverse("search_products"), {"search": "ISP Dummy"})
        detail = api_client.get(reverse("get_product_detail", args=[sku.id]))

        assert listed.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_payload = listed.data
        search_payload = search.data
        detail_payload = detail.data
        _assert_no_live_host(list_payload)
        _assert_no_live_host(search_payload)
        _assert_no_live_host(detail_payload)

        list_rows = (
            list_payload
            if isinstance(list_payload, list)
            else list_payload.get("results", list_payload)
        )
        search_rows = (
            search_payload
            if isinstance(search_payload, list)
            else search_payload.get("results", search_payload)
        )
        list_row = next(row for row in list_rows if row["id"] == sku.id)
        search_row = next(row for row in search_rows if row["id"] == sku.id)
        assert "is_perishable" not in list_row
        assert "is_perishable" not in search_row
        assert "is_perishable" not in detail_payload
        assert list_row["image"] == DUMMY_IMAGE_URL or list_row.get("image_url") == DUMMY_IMAGE_URL

    def test_unauthenticated_search_denied(self, api_client):
        _owner, shop = _make_retailer("isp_auth_own", "ISP Auth Shop")
        category = _make_category(shop, "ISP Auth Cat")
        _make_dummy_product(shop, category, "ISP Auth Milk")

        response = api_client.get(reverse("search_products"), {"search": "ISP Auth"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        _assert_no_live_host(response.data)
