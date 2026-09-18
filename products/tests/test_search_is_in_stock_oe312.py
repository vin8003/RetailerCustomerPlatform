"""
OE-312 / F follow-on — is_in_stock on retailer search.

Same Product.is_in_stock as list/detail. False stays false (do not
omit). POS no_page does not expose this field; this slice does not
add it there. Public list/search querysets still filter
is_available=True (unchanged) and do not filter is_in_stock; the
false echo is locked on the shared serializer and on public rows
for available out-of-stock SKUs. Auth/tenancy unchanged. READ only.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductBrand, ProductCategory
from products.serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8903121111111"
PRIMARY_B = "8903122222222"
MRP_ATTA = Decimal("25.50")
MRP_BISCUITS = Decimal("40.00")
STORE_ATTA = Decimal("20.00")
STORE_BISCUITS = Decimal("35.50")
GROUP_ATTA = "oe312-atta"
GROUP_BISCUITS = "oe312-biscuits"


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


def _make_brand(name):
    return ProductBrand.objects.create(name=name, is_active=True)


def _make_product(retailer, category, name, brand=None, barcode=None, **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "brand": brand,
        "barcode": barcode,
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


def _rows(payload):
    return payload if isinstance(payload, list) else payload.get("results") or []


def _row_by_id(payload, product_id):
    for row in _rows(payload):
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _pos(api_client):
    return api_client.get(reverse("get_retailer_products"), {"no_page": "true"})


def _list(api_client):
    return api_client.get(reverse("get_retailer_products"))


def _detail(api_client, product_id):
    return api_client.get(reverse("get_product_detail", args=[product_id]))


def _search(api_client, query):
    return api_client.get(reverse("search_products"), {"search": query})


def _retailer_ctx(user):
    return {
        "request": SimpleNamespace(
            user=SimpleNamespace(
                is_authenticated=True,
                user_type="retailer",
                id=getattr(user, "id", None),
            )
        )
    }


def _assert_prior_search_fields(search_row, list_row, pos_row=None):
    """Light OE-287 / 290 / 291 / 293 / 294 / 295 / 298 / 299 / 300 / 303 non-regression."""
    assert search_row["brand_name"] == list_row["brand_name"]
    assert search_row["barcode"] == list_row["barcode"]
    assert search_row["category_name"] == list_row["category_name"]
    assert search_row["original_price"] == list_row["original_price"]
    assert search_row["is_seasonal"] == list_row["is_seasonal"]
    assert search_row["product_group"] == list_row["product_group"]
    assert search_row["discounted_price"] == list_row["discounted_price"]
    assert search_row["is_featured"] == list_row["is_featured"]
    assert search_row["is_active"] == list_row["is_active"]
    assert search_row["is_available"] == list_row["is_available"]
    if pos_row is None:
        return
    assert search_row["brand_name"] == pos_row["brand_name"]
    assert search_row["barcode"] == pos_row["barcode"]
    assert search_row["category_name"] == pos_row["category_name"]
    assert Decimal(str(search_row["original_price"])) == Decimal(
        str(pos_row["original_price"])
    )
    assert search_row["is_seasonal"] == pos_row["is_seasonal"]
    assert search_row["product_group"] == pos_row["product_group"]
    assert Decimal(str(search_row["discounted_price"])) == Decimal(
        str(pos_row["discounted_price"])
    )
    assert search_row["is_active"] == pos_row["is_active"]
    assert "is_available" not in pos_row


@pytest.mark.django_db
class TestSearchIsInStock:
    def test_search_is_in_stock_matches_list_and_detail(self, api_client):
        owner, shop = _make_retailer("oe312_hit_own", "OE312 Stock Shop")
        groceries = _make_category(shop, "OE312 Groceries")
        snacks = _make_category(shop, "OE312 Snacks")
        aashirvaad = _make_brand("OE312 Aashirvaad")
        britannia = _make_brand("OE312 Britannia")
        atta = _make_product(
            shop,
            groceries,
            "OE312 Atta",
            brand=aashirvaad,
            barcode=PRIMARY_A,
            price=STORE_ATTA,
            original_price=MRP_ATTA,
            is_seasonal=True,
            is_featured=True,
            is_active=True,
            is_available=True,
            quantity=Decimal("8.000"),
            product_group=GROUP_ATTA,
        )
        biscuits = _make_product(
            shop,
            snacks,
            "OE312 Biscuits",
            brand=britannia,
            barcode=PRIMARY_B,
            price=STORE_BISCUITS,
            original_price=MRP_BISCUITS,
            is_seasonal=False,
            is_featured=False,
            is_active=True,
            is_available=True,
            quantity=Decimal("0.000"),
            product_group=GROUP_BISCUITS,
        )

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE312")
        atta_detail = _detail(api_client, atta.id)
        biscuits_detail = _detail(api_client, biscuits.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert atta_detail.status_code == status.HTTP_200_OK
        assert biscuits_detail.status_code == status.HTTP_200_OK

        for product, expected, detail in (
            (atta, True, atta_detail.data),
            (biscuits, False, biscuits_detail.data),
        ):
            list_row = _row_by_id(listed.data, product.id)
            search_row = _row_by_id(search.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            assert "is_in_stock" in search_row
            assert search_row["is_in_stock"] is expected
            assert search_row["is_in_stock"] == list_row["is_in_stock"]
            assert search_row["is_in_stock"] == detail["is_in_stock"]
            assert "is_in_stock" not in pos_row
            _assert_prior_search_fields(search_row, list_row, pos_row)

    def test_false_is_in_stock_stays_false(self, api_client):
        """Retailer HTTP search includes out-of-stock SKUs; key must stay false."""
        owner, shop = _make_retailer("oe312_false_own", "OE312 False Shop")
        category = _make_category(shop, "OE312 False Cat")
        staple = _make_product(
            shop,
            category,
            "OE312 Staple Rice",
            barcode=None,
            quantity=Decimal("0.000"),
            is_available=True,
        )
        assert staple.is_in_stock is False

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        search = _search(api_client, "OE312 Staple")
        detail = _detail(api_client, staple.id)

        assert listed.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_row = _row_by_id(listed.data, staple.id)
        search_row = _row_by_id(search.data, staple.id)
        assert "is_in_stock" in search_row
        assert search_row["is_in_stock"] is False
        assert search_row["is_in_stock"] == list_row["is_in_stock"]
        assert search_row["is_in_stock"] == detail.data["is_in_stock"]

        ctx = _retailer_ctx(owner)
        staple_refreshed = Product.objects.get(pk=staple.pk)
        list_data = ProductListSerializer(staple_refreshed, context=ctx).data
        detail_data = ProductDetailSerializer(staple_refreshed, context=ctx).data
        search_data = ProductSearchSerializer(staple_refreshed, context=ctx).data
        assert "is_in_stock" in search_data
        assert search_data["is_in_stock"] is False
        assert search_data["is_in_stock"] == list_data["is_in_stock"]
        assert search_data["is_in_stock"] == detail_data["is_in_stock"]

    def test_public_search_is_in_stock_matches_public_list(self, api_client):
        _owner, shop = _make_retailer("oe312_pub_own", "OE312 Public Shop")
        category = _make_category(shop, "OE312 Public Cat")
        featured = _make_product(
            shop,
            category,
            "OE312 Public Mango",
            brand=_make_brand("OE312 Public Brand"),
            barcode=PRIMARY_A,
            price=STORE_ATTA,
            original_price=MRP_ATTA,
            is_seasonal=True,
            is_featured=True,
            is_active=True,
            is_available=True,
            quantity=Decimal("8.000"),
            product_group=GROUP_ATTA,
        )
        oos_available = _make_product(
            shop,
            category,
            "OE312 Public OOS",
            barcode=PRIMARY_B,
            price=STORE_BISCUITS,
            original_price=MRP_BISCUITS,
            is_seasonal=False,
            is_featured=False,
            is_active=True,
            is_available=True,
            quantity=Decimal("0.000"),
            product_group=GROUP_BISCUITS,
        )
        hidden = _make_product(
            shop,
            category,
            "OE312 Public Hidden",
            barcode=None,
            price=STORE_BISCUITS,
            original_price=None,
            is_seasonal=False,
            is_featured=False,
            is_active=True,
            is_available=False,
            quantity=Decimal("8.000"),
            product_group=None,
        )

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "OE312 Public"},
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK

        featured_list = _row_by_id(public.data, featured.id)
        featured_search = _row_by_id(public_search.data, featured.id)
        assert "is_in_stock" in featured_search
        assert featured_search["is_in_stock"] == featured_list["is_in_stock"]
        assert featured_search["is_in_stock"] is True
        _assert_prior_search_fields(featured_search, featured_list)
        assert featured_search["barcode"] == PRIMARY_A
        assert featured_search["is_seasonal"] is True
        assert featured_search["is_featured"] is True
        assert featured_search["is_active"] is True
        assert featured_search["is_available"] is True
        assert featured_search["product_group"] == GROUP_ATTA

        oos_list = _row_by_id(public.data, oos_available.id)
        oos_search = _row_by_id(public_search.data, oos_available.id)
        assert "is_in_stock" in oos_search
        assert oos_search["is_in_stock"] is False
        assert oos_search["is_in_stock"] == oos_list["is_in_stock"]
        assert oos_search["is_available"] is True

        public_ids = {row["id"] for row in _rows(public.data)}
        public_search_ids = {row["id"] for row in _rows(public_search.data)}
        assert hidden.id not in public_ids
        assert hidden.id not in public_search_ids

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe312_auth_own", "OE312 Auth Shop")
        category = _make_category(shop, "OE312 Auth Cat")
        _make_product(
            shop,
            category,
            "OE312 Auth Rice",
            barcode=PRIMARY_A,
            is_available=True,
        )
        customer = _make_customer("oe312_auth_cust")

        anon_search = _search(api_client, "OE312")
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_search = _search(api_client, "OE312")
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN

    def test_search_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe312_ten_a", "OE312 Tenant A")
        owner_b, shop_b = _make_retailer("oe312_ten_b", "OE312 Tenant B")
        cat_a = _make_category(shop_a, "OE312 A Cat")
        cat_b = _make_category(shop_b, "OE312 B Cat")
        product_a = _make_product(
            shop_a,
            cat_a,
            "OE312 A SKU",
            brand=_make_brand("OE312 Brand A"),
            is_available=True,
            quantity=Decimal("8.000"),
        )
        product_b = _make_product(
            shop_b,
            cat_b,
            "OE312 B SKU",
            brand=_make_brand("OE312 Brand B"),
            is_available=True,
            quantity=Decimal("0.000"),
        )

        api_client.force_authenticate(user=owner_b)
        pos = _pos(api_client)
        search = _search(api_client, "OE312")
        detail_a = _detail(api_client, product_a.id)

        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        pos_ids = {row["id"] for row in pos.data}
        search_ids = {row["id"] for row in _rows(search.data)}
        assert product_a.id not in pos_ids
        assert product_a.id not in search_ids
        assert product_b.id in pos_ids
        assert product_b.id in search_ids
        assert _row_by_id(search.data, product_b.id)["is_in_stock"] is False
        assert "is_in_stock" not in _row_by_id(pos.data, product_b.id)
        assert _row_by_id(search.data, product_b.id)["is_available"] is True
