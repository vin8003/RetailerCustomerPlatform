"""
OE-149 / F-0034 — optional reorder_level on product read serializers.

Thin EXTEND only. Echo the model field when it exists and the caller
is a retailer; omit it when Product has no such column or the caller
is public/customer. Do not add Meta.fields (that would crash if the
field is missing). Dummy objects only — no live *.ordereasy.win.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import FieldDoesNotExist

from products.serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    ReorderLevelReadMixin,
    attach_reorder_level,
    caller_is_retailer,
    product_has_reorder_level_field,
)

_SERIALIZERS = (
    ProductListSerializer,
    ProductDetailSerializer,
    ProductSearchSerializer,
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


def _retailer_context():
    return {
        "request": SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, user_type="retailer")
        )
    }


def _customer_context():
    return {
        "request": SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, user_type="customer")
        )
    }


def _anon_context():
    return {
        "request": SimpleNamespace(
            user=SimpleNamespace(is_authenticated=False, user_type=None)
        )
    }


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


def test_attach_omits_when_include_false_even_if_field_exists():
    dummy = SimpleNamespace(reorder_level=Decimal('5'))
    data = attach_reorder_level(
        {}, dummy, model=_dummy_model({'reorder_level'}), include=False
    )
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


def test_caller_is_retailer_only_for_shop_jwt():
    assert caller_is_retailer(_retailer_context()) is True
    assert caller_is_retailer(_customer_context()) is False
    assert caller_is_retailer(_anon_context()) is False
    assert caller_is_retailer({}) is False
    assert caller_is_retailer(None) is False


def test_serializers_do_not_declare_reorder_level_on_meta():
    for serializer_cls in _SERIALIZERS:
        assert 'reorder_level' not in serializer_cls.Meta.fields
        assert ReorderLevelReadMixin in serializer_cls.__mro__


@pytest.mark.django_db
def test_list_detail_search_omit_key_when_model_has_no_field(product):
    for serializer_cls in _SERIALIZERS:
        data = serializer_cls(product, context=_retailer_context()).data
        assert 'reorder_level' not in data


@pytest.mark.django_db
@pytest.mark.parametrize(
    "value, expected",
    [
        (Decimal("8.500"), 8.5),
        (Decimal("0"), 0),
        (None, None),
    ],
)
def test_list_detail_search_echo_dummy_value_for_retailer(
    product, monkeypatch, value, expected
):
    monkeypatch.setattr(
        'products.serializers.product_has_reorder_level_field',
        lambda model=None: True,
    )
    product.reorder_level = value
    for serializer_cls in _SERIALIZERS:
        data = serializer_cls(product, context=_retailer_context()).data
        assert data['reorder_level'] == expected


@pytest.mark.django_db
def test_public_and_customer_omit_even_when_field_exists(product, monkeypatch):
    monkeypatch.setattr(
        'products.serializers.product_has_reorder_level_field',
        lambda model=None: True,
    )
    product.reorder_level = Decimal('9')
    for serializer_cls in _SERIALIZERS:
        for context in (_customer_context(), _anon_context(), {}):
            data = serializer_cls(product, context=context).data
            assert 'reorder_level' not in data
