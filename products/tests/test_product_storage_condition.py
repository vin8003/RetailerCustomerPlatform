"""
Optional storage_condition on product list/detail.

Echo Product.storage_condition when the attribute exists; omit the key
when the attribute/column is absent. Do not add storage_condition to any
serializer Meta.fields. Never invent from description, notes, or
care_instructions. Dummy / local only — never *.ordereasy.win.
Does not touch ProductSearchSerializer Meta or POS products/views.py.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import FieldDoesNotExist
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
    product_storage_condition,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

KEEP_COLD = "Keep refrigerated 2-8C"
INVENTED_FROM_COPY = "Store in a cool dry place"


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
        "description": "Dairy staple. Keep chilled after opening.",
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


class TestProductStorageConditionHelper:
    def test_product_has_no_storage_condition_field(self):
        with pytest.raises(FieldDoesNotExist):
            Product._meta.get_field("storage_condition")

    def test_missing_attribute_is_none(self):
        assert not hasattr(Product, "storage_condition")
        assert product_storage_condition(SimpleNamespace(name="no-storage")) is None

    def test_none_product_is_none(self):
        assert product_storage_condition(None) is None

    def test_present_string_is_echoed(self):
        assert product_storage_condition(
            SimpleNamespace(storage_condition=KEEP_COLD)
        ) == KEEP_COLD

    def test_null_and_empty_passthrough(self):
        assert product_storage_condition(
            SimpleNamespace(storage_condition=None)
        ) is None
        assert product_storage_condition(
            SimpleNamespace(storage_condition="")
        ) == ""

    def test_does_not_invent_from_description_notes_or_care(self):
        decoy = SimpleNamespace(
            name="decoy",
            description=INVENTED_FROM_COPY,
            notes=INVENTED_FROM_COPY,
            care_instructions=INVENTED_FROM_COPY,
        )
        assert not hasattr(decoy, "storage_condition")
        assert product_storage_condition(decoy) is None


@pytest.mark.django_db
class TestProductSerializerStorageCondition:
    def test_list_and_detail_omit_when_product_has_no_field(self, api_client):
        owner, shop = _make_retailer("sc_miss_own", "SC Missing Shop")
        category = _make_category(shop, "SC Missing Cat")
        product = _make_product(shop, category, "SC Rice")
        assert not hasattr(product, "storage_condition")

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        detail = _detail(api_client, product.id)

        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        list_row = _row_by_id(listed.data, product.id)
        assert "storage_condition" not in list_row
        assert "storage_condition" not in detail.data
        assert list_row["name"] == product.name
        assert list_row["description"] == product.description
        assert "storage_condition" not in ProductListSerializer(product).data
        assert "storage_condition" not in ProductDetailSerializer(product).data

    def test_serializer_echoes_when_attribute_exists(self):
        _owner, shop = _make_retailer("sc_echo_own", "SC Echo Shop")
        category = _make_category(shop, "SC Echo Cat")
        milk = _make_product(shop, category, "SC Milk")
        rice = _make_product(shop, category, "SC Rice Bag")
        milk.storage_condition = KEEP_COLD
        rice.storage_condition = "Store in a dry place"

        milk_list = ProductListSerializer(milk).data
        rice_list = ProductListSerializer(rice).data
        milk_detail = ProductDetailSerializer(milk).data
        rice_detail = ProductDetailSerializer(rice).data

        assert milk_list["storage_condition"] == KEEP_COLD
        assert rice_list["storage_condition"] == "Store in a dry place"
        assert milk_detail["storage_condition"] == KEEP_COLD
        assert rice_detail["storage_condition"] == "Store in a dry place"

    def test_serializer_null_passthrough_when_attribute_is_none(self):
        _owner, shop = _make_retailer("sc_null_own", "SC Null Shop")
        category = _make_category(shop, "SC Null Cat")
        product = _make_product(shop, category, "SC Sugar")
        product.storage_condition = None

        assert ProductListSerializer(product).data["storage_condition"] is None
        assert ProductDetailSerializer(product).data["storage_condition"] is None

    def test_serializer_empty_passthrough(self):
        _owner, shop = _make_retailer("sc_empty_own", "SC Empty Shop")
        category = _make_category(shop, "SC Empty Cat")
        product = _make_product(shop, category, "SC Salt")
        product.storage_condition = ""

        assert ProductListSerializer(product).data["storage_condition"] == ""
        assert ProductDetailSerializer(product).data["storage_condition"] == ""

    def test_does_not_invent_from_description_notes_or_care(self):
        _owner, shop = _make_retailer("sc_invent_own", "SC Invent Shop")
        category = _make_category(shop, "SC Invent Cat")
        product = _make_product(
            shop,
            category,
            "SC Yogurt",
            description=INVENTED_FROM_COPY,
        )
        product.notes = INVENTED_FROM_COPY
        product.care_instructions = INVENTED_FROM_COPY
        assert not hasattr(product, "storage_condition")

        list_data = ProductListSerializer(product).data
        detail_data = ProductDetailSerializer(product).data
        assert "storage_condition" not in list_data
        assert "storage_condition" not in detail_data
        assert list_data["description"] == INVENTED_FROM_COPY
        assert detail_data["description"] == INVENTED_FROM_COPY

    def test_public_list_and_detail_omit_when_missing(self, api_client):
        _owner, shop = _make_retailer("sc_pub_own", "SC Public Shop")
        category = _make_category(shop, "SC Public Cat")
        product = _make_product(shop, category, "SC Public Mango")

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_detail = api_client.get(
            reverse("get_product_detail_public", args=[shop.id, product.id])
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_detail.status_code == status.HTTP_200_OK
        row = _row_by_id(public.data, product.id)
        assert "storage_condition" not in row
        assert "storage_condition" not in public_detail.data

    def test_write_payload_storage_condition_is_ignored(self, api_client):
        owner, shop = _make_retailer("sc_write_own", "SC Write Shop")
        category = _make_category(shop, "SC Write Cat")

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("create_product"),
            {
                "name": "SC Write Milk",
                "category": category.id,
                "price": "12.00",
                "storage_condition": KEEP_COLD,
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        product = Product.objects.get(pk=created.data["id"])
        assert product.name == "SC Write Milk"
        assert Decimal(str(created.data["price"])) == Decimal("12.00")
        assert not hasattr(product, "storage_condition")
        assert "storage_condition" not in created.data

        patched = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"storage_condition": "Do not persist"},
            format="json",
        )
        assert patched.status_code == status.HTTP_200_OK, patched.data
        product.refresh_from_db()
        assert product.name == "SC Write Milk"
        assert product.price == Decimal("12.00")
        assert not hasattr(product, "storage_condition")
        assert "storage_condition" not in patched.data

        write = ProductUpdateSerializer(
            product, data={"storage_condition": "Ignored"}, partial=True
        )
        assert write.is_valid(), write.errors
        write.save()
        product.refresh_from_db()
        assert product.name == "SC Write Milk"
        assert not hasattr(product, "storage_condition")

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("sc_auth_own", "SC Auth Shop")
        category = _make_category(shop, "SC Auth Cat")
        product = _make_product(shop, category, "SC Auth Rice")
        customer = _make_customer("sc_auth_cust")

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
        _owner_a, shop_a = _make_retailer("sc_ten_a", "SC Tenant A")
        owner_b, shop_b = _make_retailer("sc_ten_b", "SC Tenant B")
        cat_a = _make_category(shop_a, "SC A Cat")
        cat_b = _make_category(shop_b, "SC B Cat")
        product_a = _make_product(shop_a, cat_a, "SC A SKU")
        product_b = _make_product(shop_b, cat_b, "SC B SKU")

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
        assert "storage_condition" not in _row_by_id(listed.data, product_b.id)
        assert "storage_condition" not in detail_b.data

    def test_serializer_adds_no_product_query(self):
        _owner, shop = _make_retailer("sc_n1_own", "SC N1 Shop")
        category = _make_category(shop, "SC N1 Cat")
        products = [
            _make_product(shop, category, f"SC N1 {idx}")
            for idx in range(3)
        ]
        loaded = list(
            Product.objects.filter(id__in=[p.id for p in products]).order_by("id")
        )
        for product, value in zip(loaded, (KEEP_COLD, "", None)):
            product.storage_condition = value

        with CaptureQueriesContext(connection) as captured:
            data = ProductListSerializer(loaded, many=True).data

        assert [row["storage_condition"] for row in data] == [KEEP_COLD, "", None]
        assert _product_table_reads(captured) == []

    def test_search_and_pos_stay_without_storage_condition(self, api_client):
        owner, shop = _make_retailer("sc_iso_own", "SC Iso Shop")
        category = _make_category(shop, "SC Iso Cat")
        product = _make_product(shop, category, "SC Iso Rice")
        product.storage_condition = KEEP_COLD
        # Instance setattr would not survive HTTP refetch; search/POS omit
        # the key because those surfaces do not use StorageConditionReadMixin.

        api_client.force_authenticate(user=owner)
        search = _search(api_client, "SC Iso")
        pos = _pos(api_client)
        assert search.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        search_row = _row_by_id(search.data, product.id)
        pos_row = _row_by_id(pos.data, product.id)
        assert "storage_condition" not in search_row
        assert "storage_condition" not in pos_row
        assert "storage_condition" not in ProductSearchSerializer(product).data

    def test_meta_fields_stay_without_storage_condition(self):
        assert "storage_condition" not in ProductListSerializer.Meta.fields
        assert "storage_condition" not in ProductDetailSerializer.Meta.fields
        assert "storage_condition" not in ProductSearchSerializer.Meta.fields
        assert "storage_condition" not in ProductCreateSerializer.Meta.fields
        assert "storage_condition" not in ProductUpdateSerializer.Meta.fields
