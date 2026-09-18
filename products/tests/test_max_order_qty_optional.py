"""
OE-359 — optional max_order_qty on product serializers if the
attribute exists. Not a Meta.fields entry. Dummy instances only.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from rest_framework import serializers

from products.serializers import (
    OptionalMaxOrderQtyMixin,
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    attach_max_order_qty,
    json_optional_qty,
)


class _DummyProductSerializer(OptionalMaxOrderQtyMixin, serializers.Serializer):
    name = serializers.CharField()


def test_json_optional_qty_none_stays_none():
    assert json_optional_qty(None) is None


def test_json_optional_qty_integral_decimal_is_int():
    assert json_optional_qty(Decimal("12.000")) == 12


def test_json_optional_qty_fractional_decimal_is_float():
    assert json_optional_qty(Decimal("2.500")) == 2.5


def test_attach_omits_when_attribute_missing():
    data = {"name": "dummy-sku"}
    attach_max_order_qty(data, SimpleNamespace(name="dummy-sku"))
    assert "max_order_qty" not in data
    assert data["name"] == "dummy-sku"


def test_attach_includes_when_attribute_present():
    data = {"name": "dummy-sku"}
    attach_max_order_qty(
        data, SimpleNamespace(name="dummy-sku", max_order_qty=Decimal("8.000"))
    )
    assert data["max_order_qty"] == 8


def test_attach_null_stays_null():
    data = {}
    attach_max_order_qty(data, SimpleNamespace(max_order_qty=None))
    assert "max_order_qty" in data
    assert data["max_order_qty"] is None


def test_dummy_serializer_includes_when_present():
    dummy = SimpleNamespace(name="dummy-rice", max_order_qty=Decimal("6.000"))
    data = _DummyProductSerializer(dummy).data
    assert data["name"] == "dummy-rice"
    assert data["max_order_qty"] == 6


def test_dummy_serializer_omits_when_absent():
    dummy = SimpleNamespace(name="dummy-wheat")
    data = _DummyProductSerializer(dummy).data
    assert data["name"] == "dummy-wheat"
    assert "max_order_qty" not in data


@pytest.mark.django_db
class TestProductSerializersOmitWithoutField:
    def test_list_detail_search_omit_when_product_has_no_attr(self, product):
        assert not hasattr(product, "max_order_qty")
        list_data = ProductListSerializer(product).data
        detail_data = ProductDetailSerializer(product).data
        search_data = ProductSearchSerializer(product).data
        assert "max_order_qty" not in list_data
        assert "max_order_qty" not in detail_data
        assert "max_order_qty" not in search_data

    def test_list_detail_search_include_when_attr_set_on_dummy_product(self, product):
        product.max_order_qty = Decimal("10.000")
        list_data = ProductListSerializer(product).data
        detail_data = ProductDetailSerializer(product).data
        search_data = ProductSearchSerializer(product).data
        assert list_data["max_order_qty"] == 10
        assert detail_data["max_order_qty"] == 10
        assert search_data["max_order_qty"] == 10
        assert "max_order_qty" not in ProductListSerializer.Meta.fields
        assert "max_order_qty" not in ProductDetailSerializer.Meta.fields
        assert "max_order_qty" not in ProductSearchSerializer.Meta.fields
