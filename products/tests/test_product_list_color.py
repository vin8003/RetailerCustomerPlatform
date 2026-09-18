"""
Optional color on Product list serializer only.

Echo getattr(instance, "color", None). Missing attr → null.
Empty string stays empty. Never invent from size / variant / name.
No DB column. Search / detail / POS Meta stay without color.
Dummy / local only.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory
from products.serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8903554111111"
PRIMARY_B = "8903554222222"


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


def _make_product(retailer, category, name, **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "price": Decimal("20.00"),
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "piece",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "results" in payload:
        return payload.get("results") or []
    if isinstance(payload, dict) and "products" in payload:
        return payload.get("products") or []
    return []


def _list_row(payload, product_id):
    for row in _rows(payload):
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from list payload")


def _list_url():
    return reverse("get_retailer_products")


def _detail_url(product_id):
    return reverse("get_product_detail", args=[product_id])


def _search_url():
    return reverse("search_products")


def _pos(api_client):
    return api_client.get(_list_url(), {"no_page": "true"})


@pytest.mark.django_db
class TestProductListColor:
    def test_missing_attr_is_null(self, api_client):
        owner, shop = _make_retailer("list_color_miss_own", "List Color Missing Shop")
        category = _make_category(shop, "List Color Missing Cat")
        product = _make_product(
            shop, category, "Navy Blue Shirt", barcode=PRIMARY_A, product_group="shirts"
        )
        product.size = "Red"
        product.specifications = {"color": "Green"}
        assert not hasattr(Product, "color")
        assert getattr(product, "color", None) is None

        api_client.force_authenticate(user=owner)
        listed = api_client.get(_list_url())
        detail = api_client.get(_detail_url(product.id))

        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        row = _list_row(listed.data, product.id)
        assert row["color"] is None
        assert ProductListSerializer(product).data["color"] is None
        assert "color" not in detail.data
        assert row["name"] == "Navy Blue Shirt"

    def test_serializer_echoes_color_when_attribute_exists(self):
        owner, shop = _make_retailer("list_color_echo_own", "List Color Echo Shop")
        category = _make_category(shop, "List Color Echo Cat")
        product = _make_product(shop, category, "Plain Tee")
        product.color = "Maroon"

        list_data = ProductListSerializer(product).data
        assert list_data["color"] == "Maroon"
        assert list_data["name"] == "Plain Tee"
        assert "color" not in ProductDetailSerializer(product).data

    def test_serializer_null_and_empty_passthrough(self):
        owner, shop = _make_retailer("list_color_empty_own", "List Color Empty Shop")
        category = _make_category(shop, "List Color Empty Cat")
        product = _make_product(shop, category, "Blank Tee")

        product.color = None
        assert ProductListSerializer(product).data["color"] is None

        product.color = ""
        assert ProductListSerializer(product).data["color"] == ""

    def test_does_not_invent_color_from_size_variant_or_name(self):
        owner, shop = _make_retailer("list_color_invent_own", "List Color Invent Shop")
        category = _make_category(shop, "List Color Invent Cat")
        red = _make_product(
            shop, category, "Red Shirt", product_group="color-shirts", barcode=PRIMARY_A
        )
        blue = _make_product(
            shop, category, "Blue Shirt", product_group="color-shirts", barcode=PRIMARY_B
        )
        red.size = "XL"
        blue.size = "S"

        red_data = ProductListSerializer(red).data
        blue_data = ProductListSerializer(blue).data
        assert red_data["color"] is None
        assert blue_data["color"] is None
        assert red_data["name"] == "Red Shirt"
        assert blue_data["name"] == "Blue Shirt"

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("list_color_auth_own", "List Color Auth Shop")
        category = _make_category(shop, "List Color Auth Cat")
        _make_product(shop, category, "List Color Auth Rice", barcode=PRIMARY_A)
        customer = _make_customer("list_color_auth_cust")

        anon = api_client.get(_list_url())
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(_list_url())
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_list_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("list_color_ten_a", "List Color Tenant A")
        owner_b, shop_b = _make_retailer("list_color_ten_b", "List Color Tenant B")
        cat_a = _make_category(shop_a, "List Color A Cat")
        cat_b = _make_category(shop_b, "List Color B Cat")
        product_a = _make_product(
            shop_a, cat_a, "List Color A SKU", barcode=PRIMARY_A
        )
        product_b = _make_product(
            shop_b, cat_b, "List Color B SKU", barcode=PRIMARY_B
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(_list_url())
        detail_a = api_client.get(_detail_url(product_a.id))

        assert listed.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        ids = {row["id"] for row in _rows(listed.data)}
        assert product_a.id not in ids
        assert product_b.id in ids
        own = _list_row(listed.data, product_b.id)
        assert own["color"] is None
        assert own["name"] == product_b.name

    def test_search_detail_pos_meta_stay_without_color(self, api_client):
        assert "color" not in ProductSearchSerializer.Meta.fields
        assert "color" not in ProductDetailSerializer.Meta.fields
        assert "color" not in ProductListSerializer.Meta.fields

        owner, shop = _make_retailer("list_color_meta_own", "List Color Meta Shop")
        category = _make_category(shop, "List Color Meta Cat")
        product = _make_product(shop, category, "List Color Meta Rice")
        product.color = "Ivory"

        api_client.force_authenticate(user=owner)
        search = api_client.get(_search_url(), {"search": "Meta Rice"})
        detail = api_client.get(_detail_url(product.id))
        pos = _pos(api_client)

        assert search.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK

        search_data = ProductSearchSerializer(product).data
        assert "color" not in search_data
        assert "color" not in detail.data
        pos_row = _list_row(pos.data, product.id)
        assert "color" not in pos_row
        search_rows = _rows(search.data)
        for row in search_rows:
            assert "color" not in row
