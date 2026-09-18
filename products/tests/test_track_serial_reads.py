"""
Optional track_serial on product read serializers.

Thin EXTEND only. Echo the model field when it exists; omit it when
Product has no such column. Do not add Meta.fields (that would crash
if the field is missing). Dummy objects only — no live *.ordereasy.win.
"""
from types import SimpleNamespace

import pytest
from django.core.exceptions import FieldDoesNotExist

from products.serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    attach_track_serial,
    product_has_track_serial_field,
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
    assert product_has_track_serial_field() is False


def test_helper_true_on_dummy_model_with_field():
    dummy_model = _dummy_model({'track_serial', 'name'})
    assert product_has_track_serial_field(dummy_model) is True


def test_helper_false_on_dummy_model_without_field():
    dummy_model = _dummy_model({'name'})
    assert product_has_track_serial_field(dummy_model) is False


def test_helper_false_on_dummy_without_meta():
    assert product_has_track_serial_field(SimpleNamespace()) is False


def test_attach_omits_key_when_field_missing():
    dummy = SimpleNamespace(track_serial=True)
    data = attach_track_serial({}, dummy, model=_dummy_model({'name'}))
    assert 'track_serial' not in data


def test_attach_echoes_dummy_true_when_field_exists():
    dummy = SimpleNamespace(track_serial=True)
    data = attach_track_serial({}, dummy, model=_dummy_model({'track_serial'}))
    assert data['track_serial'] is True


def test_attach_keeps_false_when_field_exists():
    dummy = SimpleNamespace(track_serial=False)
    data = attach_track_serial({}, dummy, model=_dummy_model({'track_serial'}))
    assert data['track_serial'] is False


def test_attach_keeps_null_when_field_exists_and_unset():
    dummy = SimpleNamespace(track_serial=None)
    data = attach_track_serial({}, dummy, model=_dummy_model({'track_serial'}))
    assert data['track_serial'] is None


def test_attach_missing_attr_on_dummy_is_null():
    dummy = SimpleNamespace()
    data = attach_track_serial({}, dummy, model=_dummy_model({'track_serial'}))
    assert data['track_serial'] is None


def test_serializers_do_not_declare_track_serial_on_meta():
    for serializer_cls in (
        ProductListSerializer,
        ProductDetailSerializer,
        ProductSearchSerializer,
    ):
        assert 'track_serial' not in serializer_cls.Meta.fields


@pytest.mark.django_db
def test_list_detail_search_omit_key_when_model_has_no_field(product):
    for serializer_cls in (
        ProductListSerializer,
        ProductDetailSerializer,
        ProductSearchSerializer,
    ):
        data = serializer_cls(product).data
        assert 'track_serial' not in data


@pytest.mark.django_db
def test_list_detail_search_echo_dummy_true_when_helper_true(product, monkeypatch):
    monkeypatch.setattr(
        'products.serializers.product_has_track_serial_field',
        lambda model=None: True,
    )
    product.track_serial = True
    for serializer_cls in (
        ProductListSerializer,
        ProductDetailSerializer,
        ProductSearchSerializer,
    ):
        data = serializer_cls(product).data
        assert data['track_serial'] is True


@pytest.mark.django_db
def test_list_detail_search_echo_dummy_false_when_helper_true(product, monkeypatch):
    monkeypatch.setattr(
        'products.serializers.product_has_track_serial_field',
        lambda model=None: True,
    )
    product.track_serial = False
    for serializer_cls in (
        ProductListSerializer,
        ProductDetailSerializer,
        ProductSearchSerializer,
    ):
        data = serializer_cls(product).data
        assert data['track_serial'] is False


@pytest.mark.django_db
def test_list_detail_search_echo_dummy_null_when_helper_true(product, monkeypatch):
    monkeypatch.setattr(
        'products.serializers.product_has_track_serial_field',
        lambda model=None: True,
    )
    product.track_serial = None
    for serializer_cls in (
        ProductListSerializer,
        ProductDetailSerializer,
        ProductSearchSerializer,
    ):
        data = serializer_cls(product).data
        assert data['track_serial'] is None


def test_dummy_payload_stays_local():
    """Dummy objects only — never call or embed *.ordereasy.win."""
    dummy = SimpleNamespace(track_serial=True)
    data = attach_track_serial(
        {'name': 'Dummy Serial Rice'},
        dummy,
        model=_dummy_model({'track_serial'}),
    )
    assert data['track_serial'] is True
    assert data['name'] == 'Dummy Serial Rice'
    assert 'ordereasy.win' not in str(data)
