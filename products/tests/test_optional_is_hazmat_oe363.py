"""
OE-363 — optional is_hazmat on product list/detail serializers.

Echo only when the instance already has the attribute. Do not add
is_hazmat to Meta.fields. Dummy objects only; no live hosts.
"""
from types import SimpleNamespace

import pytest

from products.serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    echo_optional_is_hazmat,
)


def test_helper_omits_key_when_attribute_missing():
    payload = echo_optional_is_hazmat({}, SimpleNamespace(name="dummy-sku"))
    assert "is_hazmat" not in payload


def test_helper_echoes_true_when_attribute_present():
    dummy = SimpleNamespace(is_hazmat=True)
    assert echo_optional_is_hazmat({}, dummy)["is_hazmat"] is True


def test_helper_echoes_false_when_attribute_present():
    dummy = SimpleNamespace(is_hazmat=False)
    assert echo_optional_is_hazmat({}, dummy)["is_hazmat"] is False


def test_helper_echoes_null_when_attribute_present():
    dummy = SimpleNamespace(is_hazmat=None)
    assert echo_optional_is_hazmat({}, dummy)["is_hazmat"] is None


def test_helper_does_not_use_invented_false_on_empty_dict():
    dummy = SimpleNamespace()
    payload = echo_optional_is_hazmat({"name": "dummy-rice"}, dummy)
    assert payload == {"name": "dummy-rice"}


def test_list_and_detail_meta_do_not_include_is_hazmat():
    assert "is_hazmat" not in ProductListSerializer.Meta.fields
    assert "is_hazmat" not in ProductDetailSerializer.Meta.fields
    assert "is_hazmat" not in ProductSearchSerializer.Meta.fields


@pytest.mark.django_db
def test_list_omits_is_hazmat_when_product_has_no_attribute(product):
    data = ProductListSerializer(product).data
    assert "is_hazmat" not in data
    assert data["name"] == "Test Rice 5kg"


@pytest.mark.django_db
def test_detail_omits_is_hazmat_when_product_has_no_attribute(product):
    data = ProductDetailSerializer(product).data
    assert "is_hazmat" not in data
    assert data["name"] == "Test Rice 5kg"


@pytest.mark.django_db
def test_list_echoes_true_and_false_when_dummy_attribute_set(product):
    product.is_hazmat = True
    assert ProductListSerializer(product).data["is_hazmat"] is True

    product.is_hazmat = False
    assert ProductListSerializer(product).data["is_hazmat"] is False


@pytest.mark.django_db
def test_detail_echoes_null_when_dummy_attribute_set(product):
    product.is_hazmat = None
    assert ProductDetailSerializer(product).data["is_hazmat"] is None


@pytest.mark.django_db
def test_search_stays_out_of_scope_even_when_attribute_set(product):
    product.is_hazmat = True
    data = ProductSearchSerializer(product).data
    assert "is_hazmat" not in data
