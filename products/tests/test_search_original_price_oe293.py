"""
OE-293 / F follow-on — original_price on retailer search.

Same Product.original_price as list/detail/POS no_page. Null stays
null (do not coerce to 0). Public search shares the serializer.
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

PRIMARY_A = "8902931111111"
PRIMARY_B = "8902932222222"
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
class TestSearchOriginalPrice:
    def test_search_original_price_matches_list_detail_and_pos(self, api_client):
        owner, shop = _make_retailer("oe293_hit_own", "OE293 Price Shop")
        groceries = _make_category(shop, "OE293 Groceries")
        snacks = _make_category(shop, "OE293 Snacks")
        aashirvaad = _make_brand("OE293 Aashirvaad")
        britannia = _make_brand("OE293 Britannia")
        atta = _make_product(
            shop,
            groceries,
            "OE293 Atta",
            brand=aashirvaad,
            barcode=PRIMARY_A,
            original_price=MRP_ATTA,
        )
        biscuits = _make_product(
            shop,
            snacks,
            "OE293 Biscuits",
            brand=britannia,
            barcode=PRIMARY_B,
            original_price=MRP_BISCUITS,
        )

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE293")
        atta_detail = _detail(api_client, atta.id)
        biscuits_detail = _detail(api_client, biscuits.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert atta_detail.status_code == status.HTTP_200_OK
        assert biscuits_detail.status_code == status.HTTP_200_OK

        for product, expected, detail in (
            (atta, "25.50", atta_detail.data),
            (biscuits, "40.00", biscuits_detail.data),
        ):
            list_row = _row_by_id(listed.data, product.id)
            search_row = _row_by_id(search.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            assert "original_price" in search_row
            assert search_row["original_price"] == expected
            assert search_row["original_price"] == list_row["original_price"]
            # POS no_page keeps model Decimal on APIClient.data; serializers echo string.
            assert Decimal(str(search_row["original_price"])) == Decimal(
                str(pos_row["original_price"])
            )
            assert search_row["original_price"] == detail["original_price"]
            # OE-287 / OE-290 / OE-291 light non-regression.
            assert search_row["brand_name"] == list_row["brand_name"]
            assert search_row["brand_name"] == pos_row["brand_name"]
            assert search_row["barcode"] == list_row["barcode"]
            assert search_row["barcode"] == pos_row["barcode"]
            assert search_row["category_name"] == list_row["category_name"]
            assert search_row["category_name"] == pos_row["category_name"]

    def test_null_original_price_stays_null(self, api_client):
        owner, shop = _make_retailer("oe293_null_own", "OE293 Null Shop")
        category = _make_category(shop, "OE293 Null Cat")
        loose = _make_product(
            shop, category, "OE293 Loose Rice", barcode=None, original_price=None
        )
        assert loose.original_price is None

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE293 Loose")
        detail = _detail(api_client, loose.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_row = _row_by_id(listed.data, loose.id)
        search_row = _row_by_id(search.data, loose.id)
        pos_row = _row_by_id(pos.data, loose.id)
        assert "original_price" in search_row
        assert search_row["original_price"] is None
        assert search_row["original_price"] == list_row["original_price"]
        assert search_row["original_price"] == pos_row["original_price"]
        assert search_row["original_price"] == detail.data["original_price"]
        assert search_row["original_price"] != 0
        assert search_row["original_price"] != "0.00"

    def test_public_search_original_price_matches_public_list(self, api_client):
        _owner, shop = _make_retailer("oe293_pub_own", "OE293 Public Shop")
        category = _make_category(shop, "OE293 Public Cat")
        branded = _make_product(
            shop,
            category,
            "OE293 Public Milk",
            brand=_make_brand("OE293 Public Brand"),
            barcode=PRIMARY_A,
            original_price=MRP_ATTA,
        )
        loose = _make_product(
            shop, category, "OE293 Public Loose", barcode=None, original_price=None
        )

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "OE293 Public"},
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK

        branded_list = _row_by_id(public.data, branded.id)
        branded_search = _row_by_id(public_search.data, branded.id)
        loose_list = _row_by_id(public.data, loose.id)
        loose_search = _row_by_id(public_search.data, loose.id)
        assert branded_search["original_price"] == branded_list["original_price"]
        assert branded_search["original_price"] == "25.50"
        assert loose_search["original_price"] == loose_list["original_price"]
        assert loose_search["original_price"] is None
        # Shared serializer still echoes OE-287 / OE-290 / OE-291 fields.
        assert branded_search["brand_name"] == branded_list["brand_name"]
        assert branded_search["barcode"] == branded_list["barcode"] == PRIMARY_A
        assert branded_search["category_name"] == branded_list["category_name"]

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe293_auth_own", "OE293 Auth Shop")
        category = _make_category(shop, "OE293 Auth Cat")
        _make_product(
            shop,
            category,
            "OE293 Auth Rice",
            barcode=PRIMARY_A,
            original_price=MRP_ATTA,
        )
        customer = _make_customer("oe293_auth_cust")

        anon_search = _search(api_client, "OE293")
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_search = _search(api_client, "OE293")
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN
