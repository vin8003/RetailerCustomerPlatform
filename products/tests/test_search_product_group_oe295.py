"""
OE-295 / F follow-on — product_group on search + POS no_page.

Same Product.product_group as list/detail. Empty/null stays
empty/null (do not invent). Public search shares the serializer.
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

PRIMARY_A = "8902951111111"
PRIMARY_B = "8902952222222"
MRP_ATTA = Decimal("25.50")
MRP_BISCUITS = Decimal("40.00")
GROUP_ATTA = "oe295-atta"
GROUP_BISCUITS = "oe295-biscuits"


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
class TestSearchPosProductGroup:
    def test_search_and_pos_product_group_matches_list_detail(self, api_client):
        owner, shop = _make_retailer("oe295_hit_own", "OE295 Group Shop")
        groceries = _make_category(shop, "OE295 Groceries")
        snacks = _make_category(shop, "OE295 Snacks")
        aashirvaad = _make_brand("OE295 Aashirvaad")
        britannia = _make_brand("OE295 Britannia")
        atta = _make_product(
            shop,
            groceries,
            "OE295 Atta",
            brand=aashirvaad,
            barcode=PRIMARY_A,
            original_price=MRP_ATTA,
            is_seasonal=True,
            product_group=GROUP_ATTA,
        )
        biscuits = _make_product(
            shop,
            snacks,
            "OE295 Biscuits",
            brand=britannia,
            barcode=PRIMARY_B,
            original_price=MRP_BISCUITS,
            is_seasonal=False,
            product_group=GROUP_BISCUITS,
        )

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE295")
        atta_detail = _detail(api_client, atta.id)
        biscuits_detail = _detail(api_client, biscuits.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert atta_detail.status_code == status.HTTP_200_OK
        assert biscuits_detail.status_code == status.HTTP_200_OK

        for product, expected, detail in (
            (atta, GROUP_ATTA, atta_detail.data),
            (biscuits, GROUP_BISCUITS, biscuits_detail.data),
        ):
            list_row = _row_by_id(listed.data, product.id)
            search_row = _row_by_id(search.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            assert "product_group" in search_row
            assert "product_group" in pos_row
            assert search_row["product_group"] == expected
            assert pos_row["product_group"] == expected
            assert search_row["product_group"] == list_row["product_group"]
            assert search_row["product_group"] == pos_row["product_group"]
            assert search_row["product_group"] == detail["product_group"]
            # OE-287 / OE-290 / OE-291 / OE-293 / OE-294 light non-regression.
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
            assert search_row["is_seasonal"] == list_row["is_seasonal"]
            assert search_row["is_seasonal"] == pos_row["is_seasonal"]

    def test_empty_and_null_product_group_stay_empty_null(self, api_client):
        owner, shop = _make_retailer("oe295_empty_own", "OE295 Empty Shop")
        category = _make_category(shop, "OE295 Empty Cat")
        unset = _make_product(
            shop,
            category,
            "OE295 Unset Rice",
            barcode=None,
            product_group=None,
        )
        blank = _make_product(
            shop,
            category,
            "OE295 Blank Rice",
            barcode=None,
            product_group="",
        )
        assert unset.product_group is None
        assert blank.product_group == ""

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE295")
        unset_detail = _detail(api_client, unset.id)
        blank_detail = _detail(api_client, blank.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert unset_detail.status_code == status.HTTP_200_OK
        assert blank_detail.status_code == status.HTTP_200_OK

        unset_list = _row_by_id(listed.data, unset.id)
        unset_search = _row_by_id(search.data, unset.id)
        unset_pos = _row_by_id(pos.data, unset.id)
        assert "product_group" in unset_search
        assert "product_group" in unset_pos
        assert unset_search["product_group"] is None
        assert unset_pos["product_group"] is None
        assert unset_list["product_group"] is None
        assert unset_detail.data["product_group"] is None

        blank_list = _row_by_id(listed.data, blank.id)
        blank_search = _row_by_id(search.data, blank.id)
        blank_pos = _row_by_id(pos.data, blank.id)
        assert "product_group" in blank_search
        assert "product_group" in blank_pos
        assert blank_search["product_group"] == ""
        assert blank_pos["product_group"] == ""
        assert blank_list["product_group"] == ""
        assert blank_detail.data["product_group"] == ""

    def test_public_search_product_group_matches_public_list(self, api_client):
        _owner, shop = _make_retailer("oe295_pub_own", "OE295 Public Shop")
        category = _make_category(shop, "OE295 Public Cat")
        grouped = _make_product(
            shop,
            category,
            "OE295 Public Mango",
            brand=_make_brand("OE295 Public Brand"),
            barcode=PRIMARY_A,
            original_price=MRP_ATTA,
            is_seasonal=True,
            product_group=GROUP_ATTA,
        )
        loose = _make_product(
            shop,
            category,
            "OE295 Public Rice",
            barcode=None,
            is_seasonal=False,
            product_group=None,
        )

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "OE295 Public"},
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK

        grouped_list = _row_by_id(public.data, grouped.id)
        grouped_search = _row_by_id(public_search.data, grouped.id)
        loose_list = _row_by_id(public.data, loose.id)
        loose_search = _row_by_id(public_search.data, loose.id)
        assert "product_group" in grouped_search
        assert "product_group" in loose_search
        assert grouped_search["product_group"] == grouped_list["product_group"]
        assert grouped_search["product_group"] == GROUP_ATTA
        assert loose_search["product_group"] == loose_list["product_group"]
        assert loose_search["product_group"] is None
        # Shared serializer still echoes OE-287 / OE-290 / OE-291 / OE-293 / OE-294.
        assert grouped_search["brand_name"] == grouped_list["brand_name"]
        assert grouped_search["barcode"] == grouped_list["barcode"] == PRIMARY_A
        assert grouped_search["category_name"] == grouped_list["category_name"]
        assert grouped_search["original_price"] == grouped_list["original_price"]
        assert grouped_search["is_seasonal"] == grouped_list["is_seasonal"] is True

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe295_auth_own", "OE295 Auth Shop")
        category = _make_category(shop, "OE295 Auth Cat")
        _make_product(
            shop,
            category,
            "OE295 Auth Rice",
            barcode=PRIMARY_A,
            product_group=GROUP_ATTA,
        )
        customer = _make_customer("oe295_auth_cust")

        anon_search = _search(api_client, "OE295")
        anon_pos = _pos(api_client)
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon_pos.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_search = _search(api_client, "OE295")
        cust_pos = _pos(api_client)
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN
        assert cust_pos.status_code == status.HTTP_403_FORBIDDEN

    def test_search_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe295_ten_a", "OE295 Tenant A")
        owner_b, shop_b = _make_retailer("oe295_ten_b", "OE295 Tenant B")
        cat_a = _make_category(shop_a, "OE295 A Cat")
        cat_b = _make_category(shop_b, "OE295 B Cat")
        product_a = _make_product(
            shop_a,
            cat_a,
            "OE295 A SKU",
            brand=_make_brand("OE295 Brand A"),
            product_group=GROUP_ATTA,
        )
        product_b = _make_product(
            shop_b,
            cat_b,
            "OE295 B SKU",
            brand=_make_brand("OE295 Brand B"),
            product_group=GROUP_BISCUITS,
        )

        api_client.force_authenticate(user=owner_b)
        pos = _pos(api_client)
        search = _search(api_client, "OE295")
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
        assert _row_by_id(search.data, product_b.id)["product_group"] == GROUP_BISCUITS
        assert _row_by_id(pos.data, product_b.id)["product_group"] == GROUP_BISCUITS
