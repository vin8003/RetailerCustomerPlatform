"""
OE-300 / F follow-on — is_active on retailer search.

Same Product.is_active as list/detail. False stays false (do not
omit). POS no_page already exposes this field. Retailer and public
search querysets still filter is_active=True (unchanged); the false
echo is locked on the shared serializer. Auth/tenancy unchanged.
READ only.
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

PRIMARY_A = "8903001111111"
PRIMARY_B = "8903002222222"
MRP_ATTA = Decimal("25.50")
MRP_BISCUITS = Decimal("40.00")
STORE_ATTA = Decimal("20.00")
STORE_BISCUITS = Decimal("35.50")
GROUP_ATTA = "oe300-atta"
GROUP_BISCUITS = "oe300-biscuits"


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
    """Light OE-287 / 290 / 291 / 293 / 294 / 295 / 298 / 299 non-regression."""
    assert search_row["brand_name"] == list_row["brand_name"]
    assert search_row["barcode"] == list_row["barcode"]
    assert search_row["category_name"] == list_row["category_name"]
    assert search_row["original_price"] == list_row["original_price"]
    assert search_row["is_seasonal"] == list_row["is_seasonal"]
    assert search_row["product_group"] == list_row["product_group"]
    assert search_row["discounted_price"] == list_row["discounted_price"]
    assert search_row["is_featured"] == list_row["is_featured"]
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


@pytest.mark.django_db
class TestSearchIsActive:
    def test_search_is_active_matches_list_detail_and_pos(self, api_client):
        owner, shop = _make_retailer("oe300_hit_own", "OE300 Active Shop")
        groceries = _make_category(shop, "OE300 Groceries")
        snacks = _make_category(shop, "OE300 Snacks")
        aashirvaad = _make_brand("OE300 Aashirvaad")
        britannia = _make_brand("OE300 Britannia")
        atta = _make_product(
            shop,
            groceries,
            "OE300 Atta",
            brand=aashirvaad,
            barcode=PRIMARY_A,
            price=STORE_ATTA,
            original_price=MRP_ATTA,
            is_seasonal=True,
            is_featured=True,
            is_active=True,
            product_group=GROUP_ATTA,
        )
        biscuits = _make_product(
            shop,
            snacks,
            "OE300 Biscuits",
            brand=britannia,
            barcode=PRIMARY_B,
            price=STORE_BISCUITS,
            original_price=MRP_BISCUITS,
            is_seasonal=False,
            is_featured=False,
            is_active=True,
            product_group=GROUP_BISCUITS,
        )

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE300")
        atta_detail = _detail(api_client, atta.id)
        biscuits_detail = _detail(api_client, biscuits.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert atta_detail.status_code == status.HTTP_200_OK
        assert biscuits_detail.status_code == status.HTTP_200_OK

        for product, detail in (
            (atta, atta_detail.data),
            (biscuits, biscuits_detail.data),
        ):
            list_row = _row_by_id(listed.data, product.id)
            search_row = _row_by_id(search.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            assert "is_active" in search_row
            assert search_row["is_active"] is True
            assert search_row["is_active"] == list_row["is_active"]
            assert search_row["is_active"] == pos_row["is_active"]
            assert search_row["is_active"] == detail["is_active"]
            _assert_prior_search_fields(search_row, list_row, pos_row)

    def test_false_is_active_stays_false_on_search_serializer(self, api_client):
        """Search HTTP still omits inactive SKUs; serializer must echo false."""
        owner, shop = _make_retailer("oe300_false_own", "OE300 False Shop")
        category = _make_category(shop, "OE300 False Cat")
        staple = _make_product(
            shop,
            category,
            "OE300 Staple Rice",
            barcode=None,
            is_active=False,
        )
        assert staple.is_active is False

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE300 Staple")
        detail = _detail(api_client, staple.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_row = _row_by_id(listed.data, staple.id)
        pos_row = _row_by_id(pos.data, staple.id)
        assert list_row["is_active"] is False
        assert pos_row["is_active"] is False
        assert detail.data["is_active"] is False
        search_ids = {row["id"] for row in _rows(search.data)}
        assert staple.id not in search_ids

        ctx = _retailer_ctx(owner)
        staple_refreshed = Product.objects.get(pk=staple.pk)
        list_data = ProductListSerializer(staple_refreshed, context=ctx).data
        detail_data = ProductDetailSerializer(staple_refreshed, context=ctx).data
        search_data = ProductSearchSerializer(staple_refreshed, context=ctx).data
        assert "is_active" in search_data
        assert search_data["is_active"] is False
        assert search_data["is_active"] == list_data["is_active"]
        assert search_data["is_active"] == detail_data["is_active"]

    def test_public_search_is_active_matches_public_list(self, api_client):
        _owner, shop = _make_retailer("oe300_pub_own", "OE300 Public Shop")
        category = _make_category(shop, "OE300 Public Cat")
        featured = _make_product(
            shop,
            category,
            "OE300 Public Mango",
            brand=_make_brand("OE300 Public Brand"),
            barcode=PRIMARY_A,
            price=STORE_ATTA,
            original_price=MRP_ATTA,
            is_seasonal=True,
            is_featured=True,
            is_active=True,
            product_group=GROUP_ATTA,
        )
        hidden = _make_product(
            shop,
            category,
            "OE300 Public Hidden",
            barcode=None,
            price=STORE_BISCUITS,
            original_price=None,
            is_seasonal=False,
            is_featured=False,
            is_active=False,
            product_group=None,
        )

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "OE300 Public"},
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK

        featured_list = _row_by_id(public.data, featured.id)
        featured_search = _row_by_id(public_search.data, featured.id)
        assert "is_active" in featured_search
        assert featured_search["is_active"] == featured_list["is_active"]
        assert featured_search["is_active"] is True
        _assert_prior_search_fields(featured_search, featured_list)
        assert featured_search["barcode"] == PRIMARY_A
        assert featured_search["is_seasonal"] is True
        assert featured_search["is_featured"] is True
        assert featured_search["product_group"] == GROUP_ATTA

        public_ids = {row["id"] for row in _rows(public.data)}
        public_search_ids = {row["id"] for row in _rows(public_search.data)}
        assert hidden.id not in public_ids
        assert hidden.id not in public_search_ids

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe300_auth_own", "OE300 Auth Shop")
        category = _make_category(shop, "OE300 Auth Cat")
        _make_product(
            shop,
            category,
            "OE300 Auth Rice",
            barcode=PRIMARY_A,
            is_active=True,
        )
        customer = _make_customer("oe300_auth_cust")

        anon_search = _search(api_client, "OE300")
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_search = _search(api_client, "OE300")
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN

    def test_search_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe300_ten_a", "OE300 Tenant A")
        owner_b, shop_b = _make_retailer("oe300_ten_b", "OE300 Tenant B")
        cat_a = _make_category(shop_a, "OE300 A Cat")
        cat_b = _make_category(shop_b, "OE300 B Cat")
        product_a = _make_product(
            shop_a,
            cat_a,
            "OE300 A SKU",
            brand=_make_brand("OE300 Brand A"),
            is_active=True,
        )
        product_b = _make_product(
            shop_b,
            cat_b,
            "OE300 B SKU",
            brand=_make_brand("OE300 Brand B"),
            is_active=True,
        )

        api_client.force_authenticate(user=owner_b)
        pos = _pos(api_client)
        search = _search(api_client, "OE300")
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
        assert _row_by_id(search.data, product_b.id)["is_active"] is True
        assert _row_by_id(pos.data, product_b.id)["is_active"] is True
