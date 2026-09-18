"""
Optional gross_weight on Product list serializer.

Echo Product.gross_weight only when the attribute exists. Do not add
the key to serializer Meta.fields. Missing field omits the key.
Null stays null (do not invent 0). Auth/tenancy unchanged. READ only.
Does not touch ProductSearchSerializer Meta, POS no_page, or detail.
Dummy / local only — never *.ordereasy.win.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
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
    product_gross_weight,
    product_has_gross_weight,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8903601111111"
PRIMARY_B = "8903602222222"
WEIGHT_ATTA = Decimal("1.250")
WEIGHT_RICE = Decimal("5.000")


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
    return payload if isinstance(payload, list) else payload.get("results") or []


def _list_row(payload, product_id):
    for row in _rows(payload):
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from list payload")


def _list_url():
    return reverse("get_retailer_products")


def _pos(api_client):
    return api_client.get(_list_url(), {"no_page": "true"})


def _product_table_reads(captured):
    return [
        q["sql"]
        for q in captured.captured_queries
        if 'FROM "product"' in q["sql"]
    ]


@pytest.mark.django_db
class TestProductGrossWeightHelper:
    def test_missing_attribute_is_absent(self):
        assert not hasattr(Product, "gross_weight")
        dummy = SimpleNamespace(name="no-weight")
        assert product_has_gross_weight(dummy) is False
        assert product_gross_weight(dummy) is None

    def test_none_product_is_absent(self):
        assert product_has_gross_weight(None) is False
        assert product_gross_weight(None) is None

    def test_present_value_is_echoed(self):
        dummy = SimpleNamespace(gross_weight=WEIGHT_ATTA)
        assert product_has_gross_weight(dummy) is True
        assert product_gross_weight(dummy) == WEIGHT_ATTA

    def test_null_passthrough_does_not_invent_zero(self):
        dummy = SimpleNamespace(gross_weight=None)
        assert product_has_gross_weight(dummy) is True
        assert product_gross_weight(dummy) is None
        assert product_gross_weight(dummy) != 0
        assert product_gross_weight(dummy) != Decimal("0")


@pytest.mark.django_db
class TestProductListGrossWeight:
    def test_list_omits_key_when_product_has_no_field(self, api_client):
        owner, shop = _make_retailer("list_gw_miss_own", "List GW Missing Shop")
        category = _make_category(shop, "List GW Missing Cat")
        product = _make_product(
            shop, category, "List GW Rice", barcode=PRIMARY_A
        )
        assert not hasattr(product, "gross_weight")

        api_client.force_authenticate(user=owner)
        listed = api_client.get(_list_url())

        assert listed.status_code == status.HTTP_200_OK
        row = _list_row(listed.data, product.id)
        assert "gross_weight" not in row
        assert row["name"] == product.name
        assert row["barcode"] == PRIMARY_A

    def test_serializer_echoes_weight_when_attribute_exists(self):
        owner, shop = _make_retailer("list_gw_echo_own", "List GW Echo Shop")
        category = _make_category(shop, "List GW Echo Cat")
        product = _make_product(shop, category, "List GW Atta")
        product.gross_weight = WEIGHT_ATTA

        data = ProductListSerializer(product).data
        assert "gross_weight" in data
        assert Decimal(str(data["gross_weight"])) == WEIGHT_ATTA
        assert data["name"] == "List GW Atta"

    def test_serializer_null_passthrough_when_attribute_is_none(self):
        owner, shop = _make_retailer("list_gw_null_own", "List GW Null Shop")
        category = _make_category(shop, "List GW Null Cat")
        product = _make_product(shop, category, "List GW Sugar")
        product.gross_weight = None

        data = ProductListSerializer(product).data
        assert "gross_weight" in data
        assert data["gross_weight"] is None
        assert data["gross_weight"] != 0
        assert data["gross_weight"] != "0.00"

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("list_gw_auth_own", "List GW Auth Shop")
        category = _make_category(shop, "List GW Auth Cat")
        _make_product(shop, category, "List GW Auth Rice", barcode=PRIMARY_A)
        customer = _make_customer("list_gw_auth_cust")

        anon = api_client.get(_list_url())
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(_list_url())
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_list_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("list_gw_ten_a", "List GW Tenant A")
        owner_b, shop_b = _make_retailer("list_gw_ten_b", "List GW Tenant B")
        cat_a = _make_category(shop_a, "List GW A Cat")
        cat_b = _make_category(shop_b, "List GW B Cat")
        product_a = _make_product(shop_a, cat_a, "List GW A SKU", barcode=PRIMARY_A)
        product_b = _make_product(shop_b, cat_b, "List GW B SKU", barcode=PRIMARY_B)

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(_list_url())

        assert listed.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in _rows(listed.data)}
        assert product_a.id not in ids
        assert product_b.id in ids
        own = _list_row(listed.data, product_b.id)
        assert "gross_weight" not in own
        assert own["name"] == product_b.name

    def test_list_gross_weight_adds_no_product_query(self):
        owner, shop = _make_retailer("list_gw_n1_own", "List GW N1 Shop")
        category = _make_category(shop, "List GW N1 Cat")
        products = [
            _make_product(shop, category, f"List GW N1 {idx}")
            for idx in range(3)
        ]
        for product, value in zip(products, (WEIGHT_RICE, WEIGHT_ATTA, None)):
            product.gross_weight = value

        with CaptureQueriesContext(connection) as captured:
            data = ProductListSerializer(products, many=True).data

        weights = [row.get("gross_weight") for row in data]
        assert Decimal(str(weights[0])) == WEIGHT_RICE
        assert Decimal(str(weights[1])) == WEIGHT_ATTA
        assert weights[2] is None
        assert _product_table_reads(captured) == []

    def test_product_serializers_meta_stay_without_gross_weight(self):
        assert "gross_weight" not in ProductListSerializer.Meta.fields
        assert "gross_weight" not in ProductSearchSerializer.Meta.fields
        assert "gross_weight" not in ProductDetailSerializer.Meta.fields
        assert "gross_weight" not in ProductCreateSerializer.Meta.fields
        assert "gross_weight" not in ProductUpdateSerializer.Meta.fields

    def test_detail_search_and_pos_nopage_stay_without_gross_weight(self, api_client):
        owner, shop = _make_retailer("list_gw_pos_own", "List GW POS Shop")
        category = _make_category(shop, "List GW POS Cat")
        product = _make_product(shop, category, "List GW POS Rice", barcode=PRIMARY_A)
        product.gross_weight = WEIGHT_RICE

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        search = api_client.get(reverse("search_products"), {"search": "List GW POS"})
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))

        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        pos_row = _list_row(pos.data, product.id)
        search_row = _list_row(search.data, product.id)
        assert "gross_weight" not in pos_row
        assert "gross_weight" not in search_row
        assert "gross_weight" not in detail.data
        assert "gross_weight" not in ProductDetailSerializer(product).data
        assert "gross_weight" not in ProductSearchSerializer(product).data

    def test_public_list_omits_key_when_field_missing(self, api_client):
        _owner, shop = _make_retailer("list_gw_pub_own", "List GW Public Shop")
        category = _make_category(shop, "List GW Public Cat")
        product = _make_product(
            shop, category, "List GW Public Milk", barcode=PRIMARY_A
        )

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        assert public.status_code == status.HTTP_200_OK
        row = _list_row(public.data, product.id)
        assert "gross_weight" not in row
        assert row["name"] == product.name
