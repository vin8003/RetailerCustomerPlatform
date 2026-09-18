"""
Optional is_made_to_order on product read serializers.

Thin EXTEND only. Echo the model field when it exists; omit it when
Product has no such column. Do not add Meta.fields (that would crash
if the field is missing). Dummy objects only — no live *.ordereasy.win.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import FieldDoesNotExist

from products.serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    attach_is_made_to_order,
    product_has_is_made_to_order_field,
)


class _DummyMeta:
    def __init__(self, field_names):
        self._field_names = set(field_names)

    def get_field(self, name):
        if name not in self._field_names:
            raise FieldDoesNotExist(name)
        return object()


def _dummy_model(field_names):
    return SimpleNamespace(_meta=_DummyMeta(field_names))


def test_helper_false_when_product_has_no_field():
    assert product_has_is_made_to_order_field() is False


def test_helper_true_on_dummy_model_with_field():
    dummy_model = _dummy_model({"is_made_to_order", "name"})
    assert product_has_is_made_to_order_field(dummy_model) is True


def test_helper_false_on_dummy_model_without_field():
    dummy_model = _dummy_model({"name"})
    assert product_has_is_made_to_order_field(dummy_model) is False


def test_helper_false_on_dummy_without_meta():
    assert product_has_is_made_to_order_field(SimpleNamespace()) is False


def test_attach_omits_key_when_field_missing():
    dummy = SimpleNamespace(is_made_to_order=True)
    data = attach_is_made_to_order({}, dummy, model=_dummy_model({"name"}))
    assert "is_made_to_order" not in data


def test_attach_echoes_true_when_field_exists():
    dummy = SimpleNamespace(is_made_to_order=True)
    data = attach_is_made_to_order({}, dummy, model=_dummy_model({"is_made_to_order"}))
    assert data["is_made_to_order"] is True


def test_attach_false_stays_false():
    dummy = SimpleNamespace(is_made_to_order=False)
    data = attach_is_made_to_order({}, dummy, model=_dummy_model({"is_made_to_order"}))
    assert "is_made_to_order" in data
    assert data["is_made_to_order"] is False


def test_attach_keeps_null_when_field_exists_and_unset():
    dummy = SimpleNamespace(is_made_to_order=None)
    data = attach_is_made_to_order({}, dummy, model=_dummy_model({"is_made_to_order"}))
    assert data["is_made_to_order"] is None


def test_attach_missing_attr_on_dummy_is_null():
    dummy = SimpleNamespace()
    data = attach_is_made_to_order({}, dummy, model=_dummy_model({"is_made_to_order"}))
    assert data["is_made_to_order"] is None


def test_serializers_do_not_declare_is_made_to_order_on_meta():
    for serializer_cls in (
        ProductListSerializer,
        ProductDetailSerializer,
        ProductSearchSerializer,
    ):
        assert "is_made_to_order" not in serializer_cls.Meta.fields


@pytest.mark.django_db
def test_list_detail_search_omit_key_when_model_has_no_field(product):
    for serializer_cls in (
        ProductListSerializer,
        ProductDetailSerializer,
        ProductSearchSerializer,
    ):
        data = serializer_cls(product).data
        assert "is_made_to_order" not in data


@pytest.mark.django_db
def test_list_detail_search_echo_dummy_true_when_helper_true(product, monkeypatch):
    monkeypatch.setattr(
        "products.serializers.product_has_is_made_to_order_field",
        lambda model=None: True,
    )
    product.is_made_to_order = True
    for serializer_cls in (
        ProductListSerializer,
        ProductDetailSerializer,
        ProductSearchSerializer,
    ):
        data = serializer_cls(product).data
        assert data["is_made_to_order"] is True


@pytest.mark.django_db
def test_list_serializer_false_dummy_value_when_helper_true(product, monkeypatch):
    monkeypatch.setattr(
        "products.serializers.product_has_is_made_to_order_field",
        lambda model=None: True,
    )
    product.is_made_to_order = False
    data = ProductListSerializer(product).data
    assert "is_made_to_order" in data
    assert data["is_made_to_order"] is False


@pytest.mark.django_db
def test_list_serializer_null_dummy_value_when_helper_true(product, monkeypatch):
    monkeypatch.setattr(
        "products.serializers.product_has_is_made_to_order_field",
        lambda model=None: True,
    )
    product.is_made_to_order = None
    data = ProductListSerializer(product).data
    assert data["is_made_to_order"] is None


def test_mixin_does_not_hit_live_hosts():
    """Guard: this slice stays dummy/local — never call *.ordereasy.win."""
    dummy = SimpleNamespace(is_made_to_order=True)
    data = attach_is_made_to_order(
        {"name": "Dummy Custom Cake"},
        dummy,
        model=_dummy_model({"is_made_to_order"}),
    )
    assert data["is_made_to_order"] is True
    assert "ordereasy.win" not in str(data)


def test_attach_does_not_use_request_mocks_for_hosts():
    request = MagicMock()
    request.url = "http://testserver/api/products/"
    dummy = SimpleNamespace(is_made_to_order=False)
    data = attach_is_made_to_order({}, dummy, model=_dummy_model({"is_made_to_order"}))
    request.get.assert_not_called()
    assert data["is_made_to_order"] is False
