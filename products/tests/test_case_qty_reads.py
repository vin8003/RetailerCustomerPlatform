"""
Optional case_qty on product read serializers (thin EXTEND).

Include the key only when Product (or the instance model) has a case_qty
field. Do not declare it on serializer Meta. Dummy shops only — no live
*.ordereasy.win.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

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
    product_has_case_qty_field,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

READ_SERIALIZERS = (
    ProductListSerializer,
    ProductDetailSerializer,
    ProductSearchSerializer,
)


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


def _make_product(retailer, name):
    category = ProductCategory.objects.create(name=f"{name} Cat", retailer=retailer)
    return Product.objects.create(
        retailer=retailer,
        name=name,
        category=category,
        price=Decimal("20.00"),
        quantity=Decimal("8.000"),
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="piece",
    )


def test_helper_false_on_real_product():
    assert product_has_case_qty_field(Product) is False
    assert product_has_case_qty_field() is False


def test_helper_true_when_get_field_succeeds():
    model = Mock()
    model._meta.get_field.return_value = object()
    assert product_has_case_qty_field(model) is True
    model._meta.get_field.assert_called_once_with("case_qty")


def test_helper_false_when_field_missing():
    model = Mock()
    model._meta.get_field.side_effect = FieldDoesNotExist("case_qty")
    assert product_has_case_qty_field(model) is False


def test_meta_does_not_declare_case_qty():
    for serializer_cls in READ_SERIALIZERS:
        assert "case_qty" not in serializer_cls.Meta.fields
    assert "case_qty" not in ProductCreateSerializer.Meta.fields
    assert "case_qty" not in ProductUpdateSerializer.Meta.fields


@pytest.mark.django_db
def test_omits_case_qty_when_model_field_absent(product):
    product.case_qty = Decimal("24")
    for serializer_cls in READ_SERIALIZERS:
        data = serializer_cls(product).data
        assert "case_qty" not in data


@pytest.mark.django_db
def test_includes_case_qty_when_model_field_exists(product, monkeypatch):
    monkeypatch.setattr(
        "products.serializers.product_has_case_qty_field",
        lambda model=None: True,
    )
    product.case_qty = Decimal("24")
    for serializer_cls in READ_SERIALIZERS:
        assert serializer_cls(product).data["case_qty"] == 24


@pytest.mark.django_db
def test_case_qty_null_and_fractional_match_quantity_shape(product, monkeypatch):
    monkeypatch.setattr(
        "products.serializers.product_has_case_qty_field",
        lambda model=None: True,
    )
    product.case_qty = None
    assert ProductListSerializer(product).data["case_qty"] == 0

    product.case_qty = Decimal("12.500")
    assert ProductListSerializer(product).data["case_qty"] == 12.5


def test_mixin_uses_instance_model_not_global_product(monkeypatch):
    """Instance._meta.model is what the mixin checks, not a hardcoded Product."""
    from products.serializers import OptionalCaseQtyReadMixin

    seen = {}

    def fake_has_field(model=None):
        seen["model"] = model
        return True

    monkeypatch.setattr(
        "products.serializers.product_has_case_qty_field",
        fake_has_field,
    )

    class Parent:
        def to_representation(self, instance):
            return {"id": instance.id}

    class Mixed(OptionalCaseQtyReadMixin, Parent):
        pass

    dummy_model = object()
    instance = SimpleNamespace(
        id=1,
        case_qty=Decimal("6"),
        _meta=SimpleNamespace(model=dummy_model),
    )
    data = Mixed().to_representation(instance)
    assert seen["model"] is dummy_model
    assert data["case_qty"] == 6


@pytest.mark.django_db
class TestCaseQtyHttpOmit:
    def test_list_search_detail_omit_when_field_absent(self, api_client):
        owner, shop = _make_retailer("caseqty_own", "CaseQty Dummy Shop")
        rice = _make_product(shop, "CaseQty Dummy Rice")
        api_client.force_authenticate(user=owner)

        listed = api_client.get(reverse("get_retailer_products"))
        assert listed.status_code == status.HTTP_200_OK
        rows = listed.data if isinstance(listed.data, list) else listed.data.get("results") or []
        row = next(item for item in rows if item["id"] == rice.id)
        assert "case_qty" not in row

        detail = api_client.get(reverse("get_product_detail", args=[rice.id]))
        assert detail.status_code == status.HTTP_200_OK
        assert "case_qty" not in detail.data

        search = api_client.get(reverse("search_products"), {"search": "CaseQty Dummy Rice"})
        assert search.status_code == status.HTTP_200_OK
        search_rows = (
            search.data if isinstance(search.data, list) else search.data.get("results") or []
        )
        search_row = next(item for item in search_rows if item["id"] == rice.id)
        assert "case_qty" not in search_row
