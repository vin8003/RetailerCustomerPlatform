"""
Optional is_weighted on product read serializers.

Echo only when Product has the model field. Do not add Meta.fields
(ModelSerializer would crash if the column is absent). Dummy hosts only.
No live *.ordereasy.win.
"""
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import FieldDoesNotExist
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory
from products.serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    product_model_has_is_weighted,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

DUMMY_IMAGE_URL = "https://cdn.example.test/dummy-rice.jpg"
LIVE_HOST_NEEDLE = "ordereasy.win"

READ_SERIALIZERS = (
    ProductListSerializer,
    ProductDetailSerializer,
    ProductSearchSerializer,
)


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


def _stub_is_weighted_model_field(concrete=True, many_to_many=False):
    """Keep real get_field for existing columns; only invent is_weighted."""
    real_get_field = Product._meta.get_field

    def fake_get_field(name):
        if name == "is_weighted":
            return SimpleNamespace(concrete=concrete, many_to_many=many_to_many)
        return real_get_field(name)

    return patch.object(Product._meta, "get_field", side_effect=fake_get_field)


@pytest.mark.django_db
class TestOptionalIsWeightedHelper:
    def test_model_field_is_absent_today(self):
        """Canary: current Product has no is_weighted column."""
        with pytest.raises(FieldDoesNotExist):
            Product._meta.get_field("is_weighted")
        assert product_model_has_is_weighted() is False

    def test_helper_true_for_concrete_field(self):
        with _stub_is_weighted_model_field(concrete=True, many_to_many=False):
            assert product_model_has_is_weighted() is True

    def test_helper_false_for_non_concrete_field(self):
        with _stub_is_weighted_model_field(concrete=False, many_to_many=False):
            assert product_model_has_is_weighted() is False

    def test_helper_false_for_many_to_many(self):
        with _stub_is_weighted_model_field(concrete=True, many_to_many=True):
            assert product_model_has_is_weighted() is False


@pytest.mark.django_db
class TestOptionalIsWeightedSerializers:
    @pytest.mark.parametrize("serializer_cls", READ_SERIALIZERS)
    def test_meta_fields_omit_is_weighted(self, serializer_cls):
        assert "is_weighted" not in serializer_cls.Meta.fields

    @pytest.mark.parametrize("serializer_cls", READ_SERIALIZERS)
    def test_omits_key_when_model_field_missing(self, serializer_cls, product):
        product.image_url = DUMMY_IMAGE_URL
        product.save(update_fields=["image_url"])
        product.is_weighted = True

        data = serializer_cls(product).data
        assert "is_weighted" not in data
        _assert_no_live_host(data)
        assert DUMMY_IMAGE_URL in _payload_text(data)

    @pytest.mark.parametrize("serializer_cls", READ_SERIALIZERS)
    def test_echoes_true_when_model_field_exists(self, serializer_cls, product):
        product.image_url = DUMMY_IMAGE_URL
        product.is_weighted = True

        with _stub_is_weighted_model_field():
            data = serializer_cls(product).data
        assert data["is_weighted"] is True
        _assert_no_live_host(data)

    @pytest.mark.parametrize("serializer_cls", READ_SERIALIZERS)
    def test_false_stays_false_when_model_field_exists(self, serializer_cls, product):
        product.is_weighted = False

        with _stub_is_weighted_model_field():
            data = serializer_cls(product).data
        assert "is_weighted" in data
        assert data["is_weighted"] is False
        _assert_no_live_host(data)

    @pytest.mark.parametrize("serializer_cls", READ_SERIALIZERS)
    def test_missing_instance_attr_defaults_false(self, serializer_cls, product):
        assert not hasattr(product, "is_weighted")

        with _stub_is_weighted_model_field():
            data = serializer_cls(product).data
        assert data["is_weighted"] is False


@pytest.mark.django_db
class TestOptionalIsWeightedHttpSmoke:
    def test_retailer_list_and_search_omit_key_and_stay_dummy(self, api_client):
        """Canary: HTTP omits the key while Product has no is_weighted column.

        When the column is added, invert these asserts to echo true/false
        instead of deleting this smoke.
        """
        owner, shop = _make_retailer("isw_list_own", "ISW Dummy Shop")
        category = _make_category(shop, "ISW Dummy Cat")
        sku = _make_dummy_product(shop, category, "ISW Dummy Rice")

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        search = api_client.get(reverse("search_products"), {"search": "ISW Dummy"})
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

        list_rows = list_payload if isinstance(list_payload, list) else list_payload.get("results", list_payload)
        search_rows = search_payload if isinstance(search_payload, list) else search_payload.get("results", search_payload)
        list_row = next(row for row in list_rows if row["id"] == sku.id)
        search_row = next(row for row in search_rows if row["id"] == sku.id)
        assert "is_weighted" not in list_row
        assert "is_weighted" not in search_row
        assert "is_weighted" not in detail_payload
        assert list_row["image"] == DUMMY_IMAGE_URL or list_row.get("image_url") == DUMMY_IMAGE_URL

    def test_unauthenticated_search_denied(self, api_client):
        _owner, shop = _make_retailer("isw_auth_own", "ISW Auth Shop")
        category = _make_category(shop, "ISW Auth Cat")
        _make_dummy_product(shop, category, "ISW Auth Rice")

        response = api_client.get(reverse("search_products"), {"search": "ISW Auth"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        _assert_no_live_host(response.data)
