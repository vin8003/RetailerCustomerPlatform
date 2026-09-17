"""
OE-294 / F follow-on — is_seasonal on retailer search.

Same Product.is_seasonal as list/detail/POS no_page. False stays
false (do not omit). Public search shares the serializer.
Auth/tenancy unchanged. READ only.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductBrand, ProductCategory
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8902941111111"
PRIMARY_B = "8902942222222"
MRP_ATTA = Decimal("25.50")
MRP_BISCUITS = Decimal("40.00")


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


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
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


@pytest.mark.django_db
class TestSearchIsSeasonal:
    def test_search_is_seasonal_matches_list_detail_and_pos(self, api_client):
        owner, shop = _make_retailer("oe294_hit_own", "OE294 Seasonal Shop")
        groceries = _make_category(shop, "OE294 Groceries")
        snacks = _make_category(shop, "OE294 Snacks")
        aashirvaad = _make_brand("OE294 Aashirvaad")
        britannia = _make_brand("OE294 Britannia")
        atta = _make_product(
            shop,
            groceries,
            "OE294 Atta",
            brand=aashirvaad,
            barcode=PRIMARY_A,
            original_price=MRP_ATTA,
            is_seasonal=True,
        )
        biscuits = _make_product(
            shop,
            snacks,
            "OE294 Biscuits",
            brand=britannia,
            barcode=PRIMARY_B,
            original_price=MRP_BISCUITS,
            is_seasonal=False,
        )

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE294")
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
            assert "is_seasonal" in search_row
            assert search_row["is_seasonal"] is expected
            assert search_row["is_seasonal"] == list_row["is_seasonal"]
            assert search_row["is_seasonal"] == pos_row["is_seasonal"]
            assert search_row["is_seasonal"] == detail["is_seasonal"]
            # OE-287 / OE-290 / OE-291 / OE-293 light non-regression.
            assert search_row["brand_name"] == list_row["brand_name"]
            assert search_row["brand_name"] == pos_row["brand_name"]
            assert search_row["barcode"] == list_row["barcode"]
            assert search_row["barcode"] == pos_row["barcode"]
            assert search_row["category_name"] == list_row["category_name"]
            assert search_row["category_name"] == pos_row["category_name"]
            assert search_row["original_price"] == list_row["original_price"]
            assert Decimal(str(search_row["original_price"])) == Decimal(
                str(pos_row["original_price"])
            )

    def test_false_is_seasonal_stays_false(self, api_client):
        owner, shop = _make_retailer("oe294_false_own", "OE294 False Shop")
        category = _make_category(shop, "OE294 False Cat")
        staple = _make_product(
            shop,
            category,
            "OE294 Staple Rice",
            barcode=None,
            is_seasonal=False,
        )
        assert staple.is_seasonal is False

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE294 Staple")
        detail = _detail(api_client, staple.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_row = _row_by_id(listed.data, staple.id)
        search_row = _row_by_id(search.data, staple.id)
        pos_row = _row_by_id(pos.data, staple.id)
        assert "is_seasonal" in search_row
        assert search_row["is_seasonal"] is False
        assert search_row["is_seasonal"] == list_row["is_seasonal"]
        assert search_row["is_seasonal"] == pos_row["is_seasonal"]
        assert search_row["is_seasonal"] == detail.data["is_seasonal"]
        assert search_row.get("is_seasonal") is False

    def test_public_search_is_seasonal_matches_public_list(self, api_client):
        _owner, shop = _make_retailer("oe294_pub_own", "OE294 Public Shop")
        category = _make_category(shop, "OE294 Public Cat")
        seasonal = _make_product(
            shop,
            category,
            "OE294 Public Mango",
            brand=_make_brand("OE294 Public Brand"),
            barcode=PRIMARY_A,
            original_price=MRP_ATTA,
            is_seasonal=True,
        )
        staple = _make_product(
            shop,
            category,
            "OE294 Public Rice",
            barcode=None,
            is_seasonal=False,
        )

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "OE294 Public"},
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK

        seasonal_list = _row_by_id(public.data, seasonal.id)
        seasonal_search = _row_by_id(public_search.data, seasonal.id)
        staple_list = _row_by_id(public.data, staple.id)
        staple_search = _row_by_id(public_search.data, staple.id)
        assert "is_seasonal" in seasonal_search
        assert "is_seasonal" in staple_search
        assert seasonal_search["is_seasonal"] == seasonal_list["is_seasonal"]
        assert seasonal_search["is_seasonal"] is True
        assert staple_search["is_seasonal"] == staple_list["is_seasonal"]
        assert staple_search["is_seasonal"] is False
        # Shared serializer still echoes OE-287 / OE-290 / OE-291 / OE-293 fields.
        assert seasonal_search["brand_name"] == seasonal_list["brand_name"]
        assert seasonal_search["barcode"] == seasonal_list["barcode"] == PRIMARY_A
        assert seasonal_search["category_name"] == seasonal_list["category_name"]
        assert seasonal_search["original_price"] == seasonal_list["original_price"]

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe294_auth_own", "OE294 Auth Shop")
        category = _make_category(shop, "OE294 Auth Cat")
        _make_product(
            shop,
            category,
            "OE294 Auth Rice",
            barcode=PRIMARY_A,
            is_seasonal=True,
        )
        customer = _make_customer("oe294_auth_cust")

        anon_search = _search(api_client, "OE294")
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_search = _search(api_client, "OE294")
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN

    def test_search_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe294_ten_a", "OE294 Tenant A")
        owner_b, shop_b = _make_retailer("oe294_ten_b", "OE294 Tenant B")
        cat_a = _make_category(shop_a, "OE294 A Cat")
        cat_b = _make_category(shop_b, "OE294 B Cat")
        product_a = _make_product(
            shop_a,
            cat_a,
            "OE294 A SKU",
            brand=_make_brand("OE294 Brand A"),
            is_seasonal=True,
        )
        product_b = _make_product(
            shop_b,
            cat_b,
            "OE294 B SKU",
            brand=_make_brand("OE294 Brand B"),
            is_seasonal=False,
        )

        api_client.force_authenticate(user=owner_b)
        pos = _pos(api_client)
        search = _search(api_client, "OE294")
        detail_a = _detail(api_client, product_a.id)

        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        pos_ids = {row["id"] for row in pos.data}
        search_ids = {row["id"] for row in search.data["results"]}
        assert product_a.id not in pos_ids
        assert product_a.id not in search_ids
        assert product_b.id in pos_ids
        assert product_b.id in search_ids
        assert _row_by_id(search.data, product_b.id)["is_seasonal"] is False
        assert _row_by_id(pos.data, product_b.id)["is_seasonal"] is False
