"""
OE-362 / F follow-on — optional is_fragile on product list/detail.

Echo Product.is_fragile only when the attribute exists. Missing field or
null stays null (no invented fragility). Do not add is_fragile to Meta.
Auth/tenancy unchanged. READ only. Dummy only — never *.ordereasy.win.
Does not touch ProductSearchSerializer Meta or POS products/views.py.
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
    product_is_fragile,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile


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
        "purchase_price": Decimal("10.00"),
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "piece",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _list(api_client):
    return api_client.get(reverse("get_retailer_products"))


def _detail(api_client, product_id):
    return api_client.get(reverse("get_product_detail", args=[product_id]))


def _search(api_client, query):
    return api_client.get(reverse("search_products"), {"search": query})


def _pos(api_client):
    return api_client.get(reverse("get_retailer_products"), {"no_page": "true"})


def _product_table_reads(captured):
    return [
        q["sql"]
        for q in captured.captured_queries
        if 'FROM "product"' in q["sql"]
    ]


@pytest.mark.django_db
class TestProductIsFragileHelper:
    def test_missing_attribute_is_null(self):
        assert not hasattr(Product, "is_fragile")
        assert product_is_fragile(SimpleNamespace(name="no-fragile")) is None

    def test_none_product_is_null(self):
        assert product_is_fragile(None) is None

    def test_present_true_and_false_are_echoed(self):
        assert product_is_fragile(SimpleNamespace(is_fragile=True)) is True
        assert product_is_fragile(SimpleNamespace(is_fragile=False)) is False

    def test_null_passthrough(self):
        assert product_is_fragile(SimpleNamespace(is_fragile=None)) is None


@pytest.mark.django_db
class TestProductSerializerIsFragile:
    def test_list_and_detail_null_when_product_has_no_field(self, api_client):
        owner, shop = _make_retailer("oe362_miss_own", "OE362 Missing Shop")
        category = _make_category(shop, "OE362 Missing Cat")
        product = _make_product(shop, category, "OE362 Rice")
        assert not hasattr(product, "is_fragile")

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        detail = _detail(api_client, product.id)

        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        list_row = _row_by_id(listed.data, product.id)
        assert "is_fragile" in list_row
        assert list_row["is_fragile"] is None
        assert "is_fragile" in detail.data
        assert detail.data["is_fragile"] is None
        assert list_row["name"] == product.name

    def test_serializer_echoes_is_fragile_when_attribute_exists(self):
        owner, shop = _make_retailer("oe362_echo_own", "OE362 Echo Shop")
        category = _make_category(shop, "OE362 Echo Cat")
        glass = _make_product(shop, category, "OE362 Glass Jar")
        rice = _make_product(shop, category, "OE362 Rice Bag")
        glass.is_fragile = True
        rice.is_fragile = False

        glass_list = ProductListSerializer(glass).data
        rice_list = ProductListSerializer(rice).data
        glass_detail = ProductDetailSerializer(glass).data
        rice_detail = ProductDetailSerializer(rice).data

        assert glass_list["is_fragile"] is True
        assert rice_list["is_fragile"] is False
        assert glass_detail["is_fragile"] is True
        assert rice_detail["is_fragile"] is False

    def test_serializer_null_passthrough_when_attribute_is_none(self):
        _owner, shop = _make_retailer("oe362_null_own", "OE362 Null Shop")
        category = _make_category(shop, "OE362 Null Cat")
        product = _make_product(shop, category, "OE362 Sugar")
        product.is_fragile = None

        assert ProductListSerializer(product).data["is_fragile"] is None
        assert ProductDetailSerializer(product).data["is_fragile"] is None

    def test_false_is_fragile_stays_false(self):
        _owner, shop = _make_retailer("oe362_false_own", "OE362 False Shop")
        category = _make_category(shop, "OE362 False Cat")
        product = _make_product(shop, category, "OE362 Staple")
        product.is_fragile = False

        assert ProductListSerializer(product).data["is_fragile"] is False
        assert ProductDetailSerializer(product).data["is_fragile"] is False

    def test_public_list_is_fragile_null_when_missing(self, api_client):
        _owner, shop = _make_retailer("oe362_pub_own", "OE362 Public Shop")
        category = _make_category(shop, "OE362 Public Cat")
        product = _make_product(shop, category, "OE362 Public Mango")

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_detail = api_client.get(
            reverse("get_product_detail_public", args=[shop.id, product.id])
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_detail.status_code == status.HTTP_200_OK
        row = _row_by_id(public.data, product.id)
        assert row["is_fragile"] is None
        assert public_detail.data["is_fragile"] is None

    def test_write_payload_is_fragile_is_ignored(self, api_client):
        owner, shop = _make_retailer("oe362_write_own", "OE362 Write Shop")
        category = _make_category(shop, "OE362 Write Cat")

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("create_product"),
            {
                "name": "OE362 Write Glass",
                "category": category.id,
                "price": "12.00",
                "is_fragile": True,
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        product = Product.objects.get(pk=created.data["id"])
        assert not hasattr(product, "is_fragile")
        assert created.data.get("is_fragile") is None

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe362_auth_own", "OE362 Auth Shop")
        category = _make_category(shop, "OE362 Auth Cat")
        product = _make_product(shop, category, "OE362 Auth Rice")
        customer = _make_customer("oe362_auth_cust")

        anon_list = _list(api_client)
        anon_detail = _detail(api_client, product.id)
        assert anon_list.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon_detail.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_list = _list(api_client)
        cust_detail = _detail(api_client, product.id)
        assert cust_list.status_code == status.HTTP_403_FORBIDDEN
        assert cust_detail.status_code == status.HTTP_403_FORBIDDEN

    def test_list_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe362_ten_a", "OE362 Tenant A")
        owner_b, shop_b = _make_retailer("oe362_ten_b", "OE362 Tenant B")
        cat_a = _make_category(shop_a, "OE362 A Cat")
        cat_b = _make_category(shop_b, "OE362 B Cat")
        product_a = _make_product(shop_a, cat_a, "OE362 A SKU")
        product_b = _make_product(shop_b, cat_b, "OE362 B SKU")

        api_client.force_authenticate(user=owner_b)
        listed = _list(api_client)
        detail_a = _detail(api_client, product_a.id)
        detail_b = _detail(api_client, product_b.id)

        assert listed.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        assert detail_b.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in listed.data["results"]}
        assert product_a.id not in ids
        assert product_b.id in ids
        assert _row_by_id(listed.data, product_b.id)["is_fragile"] is None

    def test_serializer_adds_no_product_query(self):
        _owner, shop = _make_retailer("oe362_n1_own", "OE362 N1 Shop")
        category = _make_category(shop, "OE362 N1 Cat")
        products = [
            _make_product(shop, category, f"OE362 N1 {idx}")
            for idx in range(3)
        ]
        loaded = list(Product.objects.filter(id__in=[p.id for p in products]).order_by("id"))
        for product, flag in zip(loaded, (True, False, None)):
            product.is_fragile = flag

        with CaptureQueriesContext(connection) as captured:
            data = ProductListSerializer(loaded, many=True).data

        assert [row["is_fragile"] for row in data] == [True, False, None]
        assert _product_table_reads(captured) == []

    def test_search_and_pos_stay_without_is_fragile(self, api_client):
        owner, shop = _make_retailer("oe362_iso_own", "OE362 Iso Shop")
        category = _make_category(shop, "OE362 Iso Cat")
        product = _make_product(shop, category, "OE362 Iso Rice")
        product.is_fragile = True

        api_client.force_authenticate(user=owner)
        search = _search(api_client, "OE362 Iso")
        pos = _pos(api_client)
        assert search.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        search_row = _row_by_id(search.data, product.id)
        pos_row = _row_by_id(pos.data, product.id)
        assert "is_fragile" not in search_row
        assert "is_fragile" not in pos_row

    def test_meta_fields_stay_without_is_fragile(self):
        assert "is_fragile" not in ProductListSerializer.Meta.fields
        assert "is_fragile" not in ProductDetailSerializer.Meta.fields
        assert "is_fragile" not in ProductSearchSerializer.Meta.fields
        assert "is_fragile" not in ProductCreateSerializer.Meta.fields
        assert "is_fragile" not in ProductUpdateSerializer.Meta.fields
