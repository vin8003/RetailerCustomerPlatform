"""
Optional size on POS no_page product dict.

Echo Product.size only when that column already exists on the model.
Do not invent a size field or value. POS no_page query flags stay intact.
Dummy shops only — never *.ordereasy.win.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import MasterProduct, Product, ProductCategory
from products.views import attach_optional_product_size, product_has_size_column
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

POS_NO_PAGE_FLAGS = (
    "is_active",
    "is_featured",
    "is_seasonal",
    "is_available",
    "in_stock",
)

POS_ROW_KEYS = (
    "id",
    "name",
    "price",
    "app_price",
    "discounted_price",
    "original_price",
    "quantity",
    "saleable_quantity",
    "track_inventory",
    "unit",
    "image",
    "category_name",
    "brand_name",
    "barcode",
    "is_active",
    "is_seasonal",
    "product_group",
    "has_batches",
    "batches",
    "group_variants",
    "is_parent_bulk",
    "parent_bulk_product",
    "conversion_factor",
    "fractional_children",
)


class _SizeField:
    name = "size"


class _DummyWithSize:
    _meta = SimpleNamespace(concrete_fields=(_SizeField(),))

    def __init__(self, size):
        self.size = size


class _DummyWithoutSize:
    _meta = SimpleNamespace(concrete_fields=())
    size = "XL"


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
        "is_featured": False,
        "is_seasonal": False,
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


def _pos(api_client, **params):
    query = {"no_page": "true"}
    query.update(params)
    return api_client.get(reverse("get_retailer_products"), query)


def _list(api_client):
    return api_client.get(reverse("get_retailer_products"))


def _detail(api_client, product_id):
    return api_client.get(reverse("get_product_detail", args=[product_id]))


class TestAttachOptionalProductSize:
    def test_omits_size_when_model_has_no_column(self):
        row = {}
        out = attach_optional_product_size(
            row, SimpleNamespace(_meta=Product._meta)
        )
        assert out is row
        assert "size" not in row
        assert product_has_size_column(Product) is False

    def test_does_not_use_setattr_or_json_as_size_column(self):
        product = SimpleNamespace(
            _meta=SimpleNamespace(concrete_fields=()),
            size="invented",
            specifications={"size": "500ml"},
        )
        row = {}
        out = attach_optional_product_size(row, product)
        assert out is row
        assert "size" not in row

    def test_echoes_existing_size_including_empty(self):
        filled = {}
        assert attach_optional_product_size(filled, _DummyWithSize("500ml")) is filled
        assert filled == {"size": "500ml"}
        empty = attach_optional_product_size({}, _DummyWithSize(""))
        assert empty == {"size": ""}
        missing = attach_optional_product_size({}, _DummyWithSize(None))
        assert missing == {"size": None}

    def test_ignores_attribute_when_column_missing(self):
        assert "size" not in attach_optional_product_size({}, _DummyWithoutSize())

    def test_precomputed_flag_overrides_instance_meta(self):
        row = attach_optional_product_size(
            {}, _DummyWithSize("L"), has_size_column=False
        )
        assert "size" not in row
        echoed = attach_optional_product_size(
            {}, _DummyWithoutSize(), has_size_column=True
        )
        assert echoed == {"size": "XL"}


@pytest.mark.django_db
class TestPosNoPageOptionalSize:
    def test_product_has_no_size_column(self):
        names = {field.name for field in Product._meta.concrete_fields}
        assert "size" not in names
        assert not hasattr(Product, "size")

    def test_pos_does_not_invent_size(self, api_client):
        owner, shop = _make_retailer("pos_size_own", "POS Size Shop")
        category = _make_category(shop, "POS Size Cat")
        product = _make_product(shop, category, "POS Size Rice")

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        detail = _detail(api_client, product.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        assert isinstance(pos.data, list)

        pos_row = _row_by_id(pos.data, product.id)
        list_row = _row_by_id(listed.data, product.id)
        assert "size" not in pos_row
        assert "size" not in list_row
        assert "size" not in detail.data

        search = api_client.get(reverse("search_products"), {"search": "POS Size Rice"})
        assert search.status_code == status.HTTP_200_OK
        search_row = _row_by_id(search.data, product.id)
        assert "size" not in search_row

    def test_pos_invokes_attach_once_per_row(self, api_client, monkeypatch):
        owner, shop = _make_retailer("pos_size_spy_own", "POS Size Spy Shop")
        category = _make_category(shop, "POS Size Spy Cat")
        first = _make_product(shop, category, "POS Size Spy One")
        second = _make_product(shop, category, "POS Size Spy Two")
        calls = []
        real = attach_optional_product_size

        def _wrap(row, product, **kwargs):
            calls.append(product.id)
            return real(row, product, **kwargs)

        monkeypatch.setattr("products.views.attach_optional_product_size", _wrap)
        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in pos.data}
        assert {first.id, second.id} <= ids
        assert calls.count(first.id) == 1
        assert calls.count(second.id) == 1
        assert "size" not in _row_by_id(pos.data, first.id)

    def test_specifications_and_master_attributes_are_not_promoted(self, api_client):
        owner, shop = _make_retailer("pos_size_spec_own", "POS Size Spec Shop")
        category = _make_category(shop, "POS Size Spec Cat")
        master = MasterProduct.objects.create(
            barcode="8900000999999",
            name="POS Size Master Oil",
            attributes={"size": "M"},
        )
        product = _make_product(
            shop,
            category,
            "POS Size Spec Oil",
            specifications={"size": "1L"},
            master_product=master,
        )

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK
        pos_row = _row_by_id(pos.data, product.id)
        assert "size" not in pos_row
        assert "specifications" not in pos_row
        assert "attributes" not in pos_row

    def test_pos_keeps_existing_row_keys(self, api_client):
        owner, shop = _make_retailer("pos_size_keys_own", "POS Size Keys Shop")
        category = _make_category(shop, "POS Size Keys Cat")
        product = _make_product(
            shop,
            category,
            "POS Size Keys Atta",
            unit="kg",
            is_active=True,
            is_seasonal=True,
            product_group="pos-size-atta",
            barcode="8900000111111",
        )

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK
        row = _row_by_id(pos.data, product.id)
        for key in POS_ROW_KEYS:
            assert key in row, key
        assert row["unit"] == "kg"
        assert row["is_active"] is True
        assert row["is_seasonal"] is True
        assert row["product_group"] == "pos-size-atta"
        assert row["barcode"] == "8900000111111"
        assert "size" not in row

    def test_pos_no_page_query_flags_still_filter(self, api_client):
        owner, shop = _make_retailer("pos_size_flag_own", "POS Size Flag Shop")
        category = _make_category(shop, "POS Size Flag Cat")
        active = _make_product(
            shop,
            category,
            "POS Size Active",
            is_active=True,
            is_featured=True,
            is_seasonal=True,
            is_available=True,
            quantity=Decimal("5.000"),
        )
        inactive = _make_product(
            shop,
            category,
            "POS Size Inactive",
            is_active=False,
            is_featured=False,
            is_seasonal=False,
            is_available=False,
            quantity=Decimal("0.000"),
        )

        api_client.force_authenticate(user=owner)

        unfiltered = _pos(api_client)
        assert unfiltered.status_code == status.HTTP_200_OK
        assert isinstance(unfiltered.data, list)
        unfiltered_ids = {row["id"] for row in unfiltered.data}
        assert active.id in unfiltered_ids
        assert inactive.id in unfiltered_ids

        for flag in POS_NO_PAGE_FLAGS:
            if flag == "in_stock":
                resp = _pos(api_client, in_stock="true")
            else:
                resp = _pos(api_client, **{flag: "true"})
            assert resp.status_code == status.HTTP_200_OK, flag
            assert isinstance(resp.data, list), flag
            ids = {row["id"] for row in resp.data}
            assert active.id in ids, flag
            assert inactive.id not in ids, flag
            for row in resp.data:
                assert "size" not in row

        for flag in POS_NO_PAGE_FLAGS:
            if flag == "in_stock":
                resp = _pos(api_client, in_stock="false")
            else:
                resp = _pos(api_client, **{flag: "false"})
            assert resp.status_code == status.HTTP_200_OK, flag
            assert isinstance(resp.data, list), flag
            ids = {row["id"] for row in resp.data}
            assert inactive.id in ids, flag
            assert active.id not in ids, flag
            for row in resp.data:
                assert "size" not in row

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("pos_size_auth_own", "POS Size Auth Shop")
        category = _make_category(shop, "POS Size Auth Cat")
        _make_product(shop, category, "POS Size Auth Rice")
        customer = _make_customer("pos_size_auth_cust")

        anon = _pos(api_client)
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust = _pos(api_client)
        assert cust.status_code == status.HTTP_403_FORBIDDEN

    def test_pos_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("pos_size_ten_a", "POS Size Tenant A")
        owner_b, shop_b = _make_retailer("pos_size_ten_b", "POS Size Tenant B")
        cat_a = _make_category(shop_a, "POS Size A Cat")
        cat_b = _make_category(shop_b, "POS Size B Cat")
        product_a = _make_product(shop_a, cat_a, "POS Size A SKU")
        product_b = _make_product(shop_b, cat_b, "POS Size B SKU")

        api_client.force_authenticate(user=owner_b)
        pos = _pos(api_client)
        detail_a = _detail(api_client, product_a.id)

        assert pos.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        ids = {row["id"] for row in pos.data}
        assert product_a.id not in ids
        assert product_b.id in ids
        assert "size" not in _row_by_id(pos.data, product_b.id)

    def test_public_catalog_unchanged(self, api_client):
        _owner, shop = _make_retailer("pos_size_pub_own", "POS Size Public Shop")
        category = _make_category(shop, "POS Size Public Cat")
        product = _make_product(shop, category, "POS Size Public Milk")

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        assert public.status_code == status.HTTP_200_OK
        row = _row_by_id(public.data, product.id)
        assert "size" not in row
        assert "saleable_quantity" not in row
        assert "margin_percent" not in row
