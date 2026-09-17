"""
OE-299 / F follow-on — is_featured on retailer search.

Same Product.is_featured as list/detail. False stays false (do not
omit). POS no_page does not expose this field; this slice does not
add it there. Public search shares the serializer.
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

PRIMARY_A = "8902991111111"
PRIMARY_B = "8902992222222"
MRP_ATTA = Decimal("25.50")
MRP_BISCUITS = Decimal("40.00")
STORE_ATTA = Decimal("20.00")
STORE_BISCUITS = Decimal("35.50")
GROUP_ATTA = "oe299-atta"
GROUP_BISCUITS = "oe299-biscuits"


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


def _assert_prior_search_fields(search_row, list_row, pos_row=None):
    """Light OE-287 / 290 / 291 / 293 / 294 / 295 / 298 non-regression."""
    assert search_row["brand_name"] == list_row["brand_name"]
    assert search_row["barcode"] == list_row["barcode"]
    assert search_row["category_name"] == list_row["category_name"]
    assert search_row["original_price"] == list_row["original_price"]
    assert search_row["is_seasonal"] == list_row["is_seasonal"]
    assert search_row["product_group"] == list_row["product_group"]
    assert search_row["discounted_price"] == list_row["discounted_price"]
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
class TestSearchIsFeatured:
    def test_search_is_featured_matches_list_and_detail(self, api_client):
        owner, shop = _make_retailer("oe299_hit_own", "OE299 Featured Shop")
        groceries = _make_category(shop, "OE299 Groceries")
        snacks = _make_category(shop, "OE299 Snacks")
        aashirvaad = _make_brand("OE299 Aashirvaad")
        britannia = _make_brand("OE299 Britannia")
        atta = _make_product(
            shop,
            groceries,
            "OE299 Atta",
            brand=aashirvaad,
            barcode=PRIMARY_A,
            price=STORE_ATTA,
            original_price=MRP_ATTA,
            is_seasonal=True,
            is_featured=True,
            product_group=GROUP_ATTA,
        )
        biscuits = _make_product(
            shop,
            snacks,
            "OE299 Biscuits",
            brand=britannia,
            barcode=PRIMARY_B,
            price=STORE_BISCUITS,
            original_price=MRP_BISCUITS,
            is_seasonal=False,
            is_featured=False,
            product_group=GROUP_BISCUITS,
        )

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE299")
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
            assert "is_featured" in search_row
            assert search_row["is_featured"] is expected
            assert search_row["is_featured"] == list_row["is_featured"]
            assert search_row["is_featured"] == detail["is_featured"]
            assert "is_featured" not in pos_row
            _assert_prior_search_fields(search_row, list_row, pos_row)

    def test_false_is_featured_stays_false(self, api_client):
        owner, shop = _make_retailer("oe299_false_own", "OE299 False Shop")
        category = _make_category(shop, "OE299 False Cat")
        staple = _make_product(
            shop,
            category,
            "OE299 Staple Rice",
            barcode=None,
            is_featured=False,
        )
        assert staple.is_featured is False

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        search = _search(api_client, "OE299 Staple")
        detail = _detail(api_client, staple.id)

        assert listed.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_row = _row_by_id(listed.data, staple.id)
        search_row = _row_by_id(search.data, staple.id)
        assert "is_featured" in search_row
        assert search_row["is_featured"] is False
        assert search_row["is_featured"] == list_row["is_featured"]
        assert search_row["is_featured"] == detail.data["is_featured"]
        assert search_row.get("is_featured") is False

    def test_public_search_is_featured_matches_public_list(self, api_client):
        _owner, shop = _make_retailer("oe299_pub_own", "OE299 Public Shop")
        category = _make_category(shop, "OE299 Public Cat")
        featured = _make_product(
            shop,
            category,
            "OE299 Public Mango",
            brand=_make_brand("OE299 Public Brand"),
            barcode=PRIMARY_A,
            price=STORE_ATTA,
            original_price=MRP_ATTA,
            is_seasonal=True,
            is_featured=True,
            product_group=GROUP_ATTA,
        )
        staple = _make_product(
            shop,
            category,
            "OE299 Public Rice",
            barcode=None,
            price=STORE_BISCUITS,
            original_price=None,
            is_seasonal=False,
            is_featured=False,
            product_group=None,
        )

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "OE299 Public"},
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK

        featured_list = _row_by_id(public.data, featured.id)
        featured_search = _row_by_id(public_search.data, featured.id)
        staple_list = _row_by_id(public.data, staple.id)
        staple_search = _row_by_id(public_search.data, staple.id)
        assert "is_featured" in featured_search
        assert "is_featured" in staple_search
        assert featured_search["is_featured"] == featured_list["is_featured"]
        assert featured_search["is_featured"] is True
        assert staple_search["is_featured"] == staple_list["is_featured"]
        assert staple_search["is_featured"] is False
        _assert_prior_search_fields(featured_search, featured_list)
        assert featured_search["barcode"] == PRIMARY_A
        assert featured_search["is_seasonal"] is True
        assert featured_search["product_group"] == GROUP_ATTA

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe299_auth_own", "OE299 Auth Shop")
        category = _make_category(shop, "OE299 Auth Cat")
        _make_product(
            shop,
            category,
            "OE299 Auth Rice",
            barcode=PRIMARY_A,
            is_featured=True,
        )
        customer = _make_customer("oe299_auth_cust")

        anon_search = _search(api_client, "OE299")
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_search = _search(api_client, "OE299")
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN

    def test_search_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe299_ten_a", "OE299 Tenant A")
        owner_b, shop_b = _make_retailer("oe299_ten_b", "OE299 Tenant B")
        cat_a = _make_category(shop_a, "OE299 A Cat")
        cat_b = _make_category(shop_b, "OE299 B Cat")
        product_a = _make_product(
            shop_a,
            cat_a,
            "OE299 A SKU",
            brand=_make_brand("OE299 Brand A"),
            is_featured=True,
        )
        product_b = _make_product(
            shop_b,
            cat_b,
            "OE299 B SKU",
            brand=_make_brand("OE299 Brand B"),
            is_featured=False,
        )

        api_client.force_authenticate(user=owner_b)
        pos = _pos(api_client)
        search = _search(api_client, "OE299")
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
        assert _row_by_id(search.data, product_b.id)["is_featured"] is False
        assert "is_featured" not in _row_by_id(pos.data, product_b.id)
