"""
Optional shelf_life_days on product list/detail serializers.

Echo Product.shelf_life_days only when the attribute exists. Missing
field or null stays null (no invented shelf life). Auth/tenancy
unchanged. READ only. Does not touch ProductSearchSerializer Meta.
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
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
    product_shelf_life_days,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

SHELF_ATTA = 180
SHELF_MILK = 7


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


def _pos(api_client):
    return api_client.get(reverse("get_retailer_products"), {"no_page": "true"})


def _detail(api_client, product_id):
    return api_client.get(reverse("get_product_detail", args=[product_id]))


def _search(api_client, query):
    return api_client.get(reverse("search_products"), {"search": query})


def _product_table_reads(captured):
    return [
        q["sql"]
        for q in captured.captured_queries
        if 'FROM "product"' in q["sql"]
    ]


@pytest.mark.django_db
class TestProductShelfLifeDaysHelper:
    def test_missing_attribute_is_null(self):
        assert not hasattr(Product, "shelf_life_days")
        assert product_shelf_life_days(SimpleNamespace(name="no-shelf")) is None

    def test_none_product_is_null(self):
        assert product_shelf_life_days(None) is None

    def test_present_value_is_echoed(self):
        assert product_shelf_life_days(SimpleNamespace(shelf_life_days=SHELF_ATTA)) == (
            SHELF_ATTA
        )

    def test_null_and_zero_passthrough(self):
        assert product_shelf_life_days(SimpleNamespace(shelf_life_days=None)) is None
        assert product_shelf_life_days(SimpleNamespace(shelf_life_days=0)) == 0


@pytest.mark.django_db
class TestProductSerializerShelfLifeDays:
    def test_list_detail_pos_null_when_product_has_no_field(self, api_client):
        owner, shop = _make_retailer("shelf_miss_own", "Shelf Missing Shop")
        category = _make_category(shop, "Shelf Missing Cat")
        atta = _make_product(shop, category, "Shelf Atta")
        milk = _make_product(shop, category, "Shelf Milk")
        assert not hasattr(atta, "shelf_life_days")
        assert not hasattr(milk, "shelf_life_days")

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        atta_detail = _detail(api_client, atta.id)
        milk_detail = _detail(api_client, milk.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert atta_detail.status_code == status.HTTP_200_OK
        assert milk_detail.status_code == status.HTTP_200_OK

        for product, detail in ((atta, atta_detail.data), (milk, milk_detail.data)):
            list_row = _row_by_id(listed.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            assert "shelf_life_days" in list_row
            assert list_row["shelf_life_days"] is None
            assert detail["shelf_life_days"] is None
            # POS no_page is a hand-built dict (OE-286 / OE-302 lock).
            assert "shelf_life_days" not in pos_row

    def test_serializer_echoes_shelf_life_when_attribute_exists(self):
        _owner, shop = _make_retailer("shelf_echo_own", "Shelf Echo Shop")
        category = _make_category(shop, "Shelf Echo Cat")
        atta = _make_product(shop, category, "Shelf Echo Atta")
        atta.shelf_life_days = SHELF_ATTA

        assert ProductListSerializer(atta).data["shelf_life_days"] == SHELF_ATTA
        assert ProductDetailSerializer(atta).data["shelf_life_days"] == SHELF_ATTA

    def test_serializer_null_and_zero_passthrough(self):
        _owner, shop = _make_retailer("shelf_null_own", "Shelf Null Shop")
        category = _make_category(shop, "Shelf Null Cat")
        loose = _make_product(shop, category, "Shelf Loose Rice")
        loose.shelf_life_days = None
        zero = _make_product(shop, category, "Shelf Zero Days")
        zero.shelf_life_days = 0

        assert ProductListSerializer(loose).data["shelf_life_days"] is None
        assert ProductDetailSerializer(loose).data["shelf_life_days"] is None
        assert ProductListSerializer(zero).data["shelf_life_days"] == 0
        assert ProductDetailSerializer(zero).data["shelf_life_days"] == 0

    def test_write_payload_shelf_life_days_is_ignored(self, api_client):
        owner, shop = _make_retailer("shelf_write_own", "Shelf Write Shop")
        category = _make_category(shop, "Shelf Write Cat")

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("create_product"),
            {
                "name": "Shelf Write Atta",
                "category": category.id,
                "price": "20.00",
                "quantity": 8,
                "unit": "piece",
                "shelf_life_days": 999,
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        assert created.data["shelf_life_days"] is None
        product = Product.objects.get(id=created.data["id"])
        assert not hasattr(product, "shelf_life_days")

        updated = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"shelf_life_days": 30},
            format="json",
        )
        assert updated.status_code == status.HTTP_200_OK, updated.data
        product.refresh_from_db()
        assert not hasattr(product, "shelf_life_days")
        assert updated.data["shelf_life_days"] is None

    def test_public_list_has_field_public_search_does_not(self, api_client):
        _owner, shop = _make_retailer("shelf_pub_own", "Shelf Public Shop")
        category = _make_category(shop, "Shelf Public Cat")
        milk = _make_product(shop, category, "Shelf Public Milk")

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "Shelf Public"},
        )
        public_detail = api_client.get(
            reverse("get_product_detail_public", args=[shop.id, milk.id])
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK
        assert public_detail.status_code == status.HTTP_200_OK

        list_row = _row_by_id(public.data, milk.id)
        search_row = _row_by_id(public_search.data, milk.id)
        assert list_row["shelf_life_days"] is None
        assert public_detail.data["shelf_life_days"] is None
        assert "shelf_life_days" not in search_row

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("shelf_auth_own", "Shelf Auth Shop")
        category = _make_category(shop, "Shelf Auth Cat")
        product = _make_product(shop, category, "Shelf Auth Rice")
        customer = _make_customer("shelf_auth_cust")

        anon_list = _list(api_client)
        anon_detail = _detail(api_client, product.id)
        assert anon_list.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon_detail.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_list = _list(api_client)
        cust_detail = _detail(api_client, product.id)
        assert cust_list.status_code == status.HTTP_403_FORBIDDEN
        assert cust_detail.status_code == status.HTTP_403_FORBIDDEN

    def test_list_and_detail_stay_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("shelf_ten_a", "Shelf Tenant A")
        owner_b, shop_b = _make_retailer("shelf_ten_b", "Shelf Tenant B")
        cat_a = _make_category(shop_a, "Shelf A Cat")
        cat_b = _make_category(shop_b, "Shelf B Cat")
        product_a = _make_product(shop_a, cat_a, "Shelf A SKU")
        product_b = _make_product(shop_b, cat_b, "Shelf B SKU")

        api_client.force_authenticate(user=owner_b)
        listed = _list(api_client)
        pos = _pos(api_client)
        detail_a = _detail(api_client, product_a.id)
        detail_b = _detail(api_client, product_b.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        assert detail_b.status_code == status.HTTP_200_OK
        list_ids = {row["id"] for row in listed.data["results"]}
        pos_ids = {row["id"] for row in pos.data}
        assert product_a.id not in list_ids
        assert product_a.id not in pos_ids
        assert product_b.id in list_ids
        assert product_b.id in pos_ids
        assert detail_b.data["shelf_life_days"] is None

    def test_loaded_product_echo_adds_no_query(self):
        _owner, shop = _make_retailer("shelf_n1_own", "Shelf N1 Shop")
        category = _make_category(shop, "Shelf N1 Cat")
        products = [
            _make_product(shop, category, f"Shelf N1 {idx}") for idx in range(3)
        ]
        loaded = list(Product.objects.filter(id__in=[p.id for p in products]).order_by("id"))
        for product, days in zip(loaded, (SHELF_ATTA, SHELF_MILK, None)):
            product.shelf_life_days = days

        with CaptureQueriesContext(connection) as captured:
            data = ProductListSerializer(loaded, many=True).data

        assert [row["shelf_life_days"] for row in data] == [
            SHELF_ATTA,
            SHELF_MILK,
            None,
        ]
        assert _product_table_reads(captured) == []

    def test_product_search_serializer_meta_stays_without_shelf_life(self):
        assert "shelf_life_days" not in ProductSearchSerializer.Meta.fields

    def test_retailer_search_and_pos_omit_shelf_life_days(self, api_client):
        owner, shop = _make_retailer("shelf_search_own", "Shelf Search Shop")
        category = _make_category(shop, "Shelf Search Cat")
        atta = _make_product(shop, category, "Shelf Search Atta")

        api_client.force_authenticate(user=owner)
        search = _search(api_client, "Shelf Search")
        listed = _list(api_client)
        pos = _pos(api_client)

        assert search.status_code == status.HTTP_200_OK
        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        search_row = _row_by_id(search.data, atta.id)
        list_row = _row_by_id(listed.data, atta.id)
        pos_row = _row_by_id(pos.data, atta.id)
        assert "shelf_life_days" not in search_row
        assert "shelf_life_days" not in pos_row
        assert list_row["shelf_life_days"] is None
