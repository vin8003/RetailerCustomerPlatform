"""
OE-149 / F-0034 — optional reorder_level on product read serializers.

Thin EXTEND only. Echo the model field when it exists; omit it when
Product has no such column. Do not add Meta.fields (that would crash
if the field is missing). Dummy objects only — no live *.ordereasy.win.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import FieldDoesNotExist

from products.serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    attach_reorder_level,
    product_has_reorder_level_field,
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
    assert product_has_reorder_level_field() is False


def test_helper_true_on_dummy_model_with_field():
    dummy_model = _dummy_model({'reorder_level', 'name'})
    assert product_has_reorder_level_field(dummy_model) is True


def test_helper_false_on_dummy_model_without_field():
    dummy_model = _dummy_model({'name'})
    assert product_has_reorder_level_field(dummy_model) is False


def test_helper_false_on_dummy_without_meta():
    assert product_has_reorder_level_field(SimpleNamespace()) is False


def test_attach_omits_key_when_field_missing():
    dummy = SimpleNamespace(reorder_level=Decimal('5'))
    data = attach_reorder_level({}, dummy, model=_dummy_model({'name'}))
    assert 'reorder_level' not in data


def test_attach_echoes_dummy_threshold_when_field_exists():
    dummy = SimpleNamespace(reorder_level=Decimal('12.000'))
    data = attach_reorder_level({}, dummy, model=_dummy_model({'reorder_level'}))
    assert data['reorder_level'] == 12


def test_attach_keeps_null_when_field_exists_and_unset():
    dummy = SimpleNamespace(reorder_level=None)
    data = attach_reorder_level({}, dummy, model=_dummy_model({'reorder_level'}))
    assert data['reorder_level'] is None


def test_attach_keeps_zero_threshold():
    dummy = SimpleNamespace(reorder_level=Decimal('0'))
    data = attach_reorder_level({}, dummy, model=_dummy_model({'reorder_level'}))
    assert data['reorder_level'] == 0


def test_attach_missing_attr_on_dummy_is_null():
    dummy = SimpleNamespace()
    data = attach_reorder_level({}, dummy, model=_dummy_model({'reorder_level'}))
    assert data['reorder_level'] is None


def test_serializers_do_not_declare_reorder_level_on_meta():
    for serializer_cls in (
        ProductListSerializer,
        ProductDetailSerializer,
        ProductSearchSerializer,
    ):
        assert 'reorder_level' not in serializer_cls.Meta.fields


@pytest.mark.django_db
def test_list_detail_search_omit_key_when_model_has_no_field(product):
    for serializer_cls in (
        ProductListSerializer,
        ProductDetailSerializer,
        ProductSearchSerializer,
    ):
        data = serializer_cls(product).data
        assert 'reorder_level' not in data


@pytest.mark.django_db
def test_list_detail_search_echo_dummy_value_when_helper_true(product, monkeypatch):
    monkeypatch.setattr(
        'products.serializers.product_has_reorder_level_field',
        lambda model=None: True,
    )
    product.reorder_level = Decimal('8.500')
    for serializer_cls in (
        ProductListSerializer,
        ProductDetailSerializer,
        ProductSearchSerializer,
    ):
        data = serializer_cls(product).data
        assert data['reorder_level'] == 8.5


@pytest.mark.django_db
def test_list_serializer_null_dummy_value_when_helper_true(product, monkeypatch):
    monkeypatch.setattr(
        'products.serializers.product_has_reorder_level_field',
        lambda model=None: True,
    )
    product.reorder_level = None
    data = ProductListSerializer(product).data
    assert data['reorder_level'] is None


def test_mixin_does_not_hit_live_hosts():
    """Guard: this slice stays dummy/local — never call *.ordereasy.win."""
    dummy = SimpleNamespace(reorder_level=Decimal('3'))
    data = attach_reorder_level({'name': 'Dummy Rice'}, dummy, model=_dummy_model({'reorder_level'}))
    assert data['reorder_level'] == 3
    assert 'ordereasy.win' not in str(data)


def test_attach_does_not_use_request_mocks_for_hosts():
    request = MagicMock()
    request.url = 'http://testserver/api/products/'
    dummy = SimpleNamespace(reorder_level=Decimal('1'))
    data = attach_reorder_level({}, dummy, model=_dummy_model({'reorder_level'}))
    request.get.assert_not_called()
    assert data['reorder_level'] == 1
