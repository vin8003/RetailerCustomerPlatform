"""
OE-290 / F follow-on — barcode on retailer search.

Same Product.barcode as list/detail/POS no_page. Empty/null stays
empty/null (mirror list). Public search shares the serializer.
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

PRIMARY_A = "8902901111111"
PRIMARY_B = "8902902222222"


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
class TestSearchBarcode:
    def test_search_barcode_matches_list_detail_and_pos(self, api_client):
        owner, shop = _make_retailer("oe290_hit_own", "OE290 Barcode Shop")
        category = _make_category(shop, "OE290 Barcode Cat")
        aashirvaad = _make_brand("OE290 Aashirvaad")
        britannia = _make_brand("OE290 Britannia")
        atta = _make_product(
            shop, category, "OE290 Atta", brand=aashirvaad, barcode=PRIMARY_A
        )
        biscuits = _make_product(
            shop, category, "OE290 Biscuits", brand=britannia, barcode=PRIMARY_B
        )

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE290")
        atta_detail = _detail(api_client, atta.id)
        biscuits_detail = _detail(api_client, biscuits.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert atta_detail.status_code == status.HTTP_200_OK
        assert biscuits_detail.status_code == status.HTTP_200_OK

        for product, expected, detail in (
            (atta, PRIMARY_A, atta_detail.data),
            (biscuits, PRIMARY_B, biscuits_detail.data),
        ):
            list_row = _row_by_id(listed.data, product.id)
            search_row = _row_by_id(search.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            assert "barcode" in search_row
            assert search_row["barcode"] == expected
            assert search_row["barcode"] == list_row["barcode"]
            assert search_row["barcode"] == pos_row["barcode"]
            assert search_row["barcode"] == detail["barcode"]
            # OE-287 light non-regression: brand_name still echoes.
            assert search_row["brand_name"] == list_row["brand_name"]
            assert search_row["brand_name"] == pos_row["brand_name"]
            assert search_row["brand_name"] == detail["brand_name"]

    def test_null_and_empty_barcode_passthrough(self, api_client):
        owner, shop = _make_retailer("oe290_null_own", "OE290 Null Shop")
        category = _make_category(shop, "OE290 Null Cat")
        loose = _make_product(shop, category, "OE290 Loose Rice", barcode=None)
        blank = _make_product(shop, category, "OE290 Blank Atta", barcode="")
        assert loose.barcode is None
        assert blank.barcode == ""

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE290")
        loose_detail = _detail(api_client, loose.id)
        blank_detail = _detail(api_client, blank.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert loose_detail.status_code == status.HTTP_200_OK
        assert blank_detail.status_code == status.HTTP_200_OK

        for product, detail in (
            (loose, loose_detail.data),
            (blank, blank_detail.data),
        ):
            list_row = _row_by_id(listed.data, product.id)
            search_row = _row_by_id(search.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            assert search_row["barcode"] == list_row["barcode"]
            assert search_row["barcode"] == pos_row["barcode"]
            assert search_row["barcode"] == detail["barcode"]
            assert search_row["barcode"] == product.barcode

    def test_public_search_barcode_matches_public_list(self, api_client):
        _owner, shop = _make_retailer("oe290_pub_own", "OE290 Public Shop")
        category = _make_category(shop, "OE290 Public Cat")
        branded = _make_product(
            shop,
            category,
            "OE290 Public Milk",
            brand=_make_brand("OE290 Public Brand"),
            barcode=PRIMARY_A,
        )
        loose = _make_product(shop, category, "OE290 Public Loose", barcode=None)

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "OE290 Public"},
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK

        branded_list = _row_by_id(public.data, branded.id)
        branded_search = _row_by_id(public_search.data, branded.id)
        loose_list = _row_by_id(public.data, loose.id)
        loose_search = _row_by_id(public_search.data, loose.id)
        assert branded_search["barcode"] == branded_list["barcode"] == PRIMARY_A
        assert loose_search["barcode"] == loose_list["barcode"]
        assert loose_search["barcode"] is None
        # Shared serializer still echoes OE-287 brand_name.
        assert branded_search["brand_name"] == branded_list["brand_name"]

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe290_auth_own", "OE290 Auth Shop")
        category = _make_category(shop, "OE290 Auth Cat")
        _make_product(shop, category, "OE290 Auth Rice", barcode=PRIMARY_A)
        customer = _make_customer("oe290_auth_cust")

        anon_search = _search(api_client, "OE290")
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_search = _search(api_client, "OE290")
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN
